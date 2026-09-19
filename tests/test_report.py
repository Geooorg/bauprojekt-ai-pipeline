"""Tests für bauprojekt.report – ohne echtes Sprachmodell.

``FunctionModel`` spielt das Sprachmodell: Eine Python-Funktion bekommt die Nachrichten
und liefert die Antwort. So lässt sich gezielt testen, was bei guten, erfundenen oder
falsch zitierten Belegen passiert – ohne API-Schlüssel, Netz und Kosten.
"""

from datetime import UTC, date, datetime
from typing import Any

import psycopg
import pytest
from conftest import FakeEncoder, basis, make_document
from pydantic_ai import UnexpectedModelBehavior
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    ToolCallPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.output import NativeOutput
from pydantic_ai.profiles import ModelProfile

from bauprojekt.config import LLM_MAX_TOKENS, LLM_TIMEOUT
from bauprojekt.db import upsert_chunks
from bauprojekt.models import Chunk, DocType, Document, Segment, SegmentKind
from bauprojekt.report import (
    Sources,
    analyze,
    check_sources,
    collect_evidence,
    format_sources,
    model_settings,
    output_spec,
    parse_thinking,
)
from bauprojekt.report_markdown import render_markdown, thousands
from bauprojekt.risks import (
    Evidence,
    Fact,
    Level,
    Risk,
    RiskAnalysis,
    RiskCategory,
    RiskReport,
    RiskStatus,
)

JETZT = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)

PROTOKOLL = make_document(
    file_name="2026-09-15_baubesprechung.docx",
    doc_type=DocType.PROTOKOLL,
    media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
)
BERICHT_43 = make_document(
    file_name="statusbericht_2026-09.pdf",
    doc_type=DocType.STATUSBERICHT,
    media_type="application/pdf",
    project_id="BAU-43",
)


def chunk(text: str, *, index: int = 0, document: Document = PROTOKOLL) -> Chunk:
    segment = Segment.create(
        document=document,
        index=index,
        kind=SegmentKind.TABELLENZEILE,
        locator=f"TOP {index + 1}",
        heading="Tagesordnungspunkte",
        text=text,
    )
    return Chunk.create(
        document=document,
        segment=segment,
        index=index,
        text=text,
        char_start=0,
        char_end=len(text),
    )


BRANDSCHUTZ = chunk(
    "TOP: 3\nThema: Brandschutzprüfung\nSachstand: Kein Verantwortlicher benannt.",
    index=2,
)
GENEHMIGUNG = chunk(
    "TOP: 4\nThema: Baugenehmigung Haus B\nSachstand: Der Antrag ruht, Prüfbericht fehlt.",
    index=3,
)
FREMD = chunk("Baugenehmigung vollständig erteilt.", document=BERICHT_43)


def risiko(*belege: tuple[str, str]) -> dict[str, Any]:
    """Ein Risiko als JSON-Argumente, wie das Sprachmodell sie liefern würde."""
    return {
        "title": "Baugenehmigung Haus B ruht",
        "category": "genehmigung",
        "description": "Der Antrag ruht, weil der Prüfbericht Brandschutz fehlt.",
        "project_area": "Haus B",
        "impact": "Baubeginn Haus B verschiebt sich.",
        "probability": "hoch",
        "severity": "hoch",
        "owner": "nicht benannt",
        "measure": "Verantwortlichen für die Brandschutzprüfung benennen.",
        "status": "eingetreten",
        "facts": [
            {
                "statement": "Der Antrag ruht.",
                "evidence": [
                    {"chunk_id": cid, "excerpt": auszug} for cid, auszug in belege
                ],
            }
        ],
        "conclusions": [
            "Ohne Verantwortlichen kein Prüfbericht, ohne Prüfbericht keine Genehmigung."
        ],
        "uncertainties": [],
    }


def antwort(*risiken: dict[str, Any]) -> Any:
    """FunctionModel, das immer dieselbe strukturierte Antwort liefert."""

    def modell(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, {"risks": list(risiken)})]
        )

    return modell


GUTER_BELEG = (GENEHMIGUNG.chunk_id, "Der Antrag ruht, Prüfbericht fehlt.")


def analyse(*belege: tuple[str, str]) -> RiskAnalysis:
    return RiskAnalysis(
        risks=[
            Risk(
                title="Baugenehmigung Haus B ruht",
                category=RiskCategory.GENEHMIGUNG,
                description="…",
                project_area="Haus B",
                impact="…",
                probability=Level.HOCH,
                severity=Level.HOCH,
                owner="nicht benannt",
                measure="…",
                status=RiskStatus.EINGETRETEN,
                facts=[
                    Fact(
                        statement="Der Antrag ruht.",
                        evidence=[Evidence(chunk_id=c, excerpt=a) for c, a in belege],
                    )
                ],
            )
        ]
    )


QUELLEN = Sources(
    project_id="BAU-42",
    chunks={c.chunk_id: c for c in (BRANDSCHUTZ, GENEHMIGUNG, FREMD)},
)


class TestQuellenpruefung:
    def test_korrekter_beleg(self) -> None:
        assert check_sources(analyse(GUTER_BELEG), QUELLEN) == []

    def test_erfundene_quelle(self) -> None:
        [fehler] = check_sources(analyse(("0" * 32, "Der Antrag ruht")), QUELLEN)
        assert "nicht geliefert" in fehler

    def test_quelle_aus_fremdem_projekt(self) -> None:
        [fehler] = check_sources(
            analyse((FREMD.chunk_id, "Baugenehmigung vollständig erteilt.")), QUELLEN
        )
        assert "gehört nicht zu BAU-42" in fehler

    def test_veraenderter_auszug(self) -> None:
        """Umformuliert ist nicht zitiert: „ist ruhend“ steht so nirgends."""
        [fehler] = check_sources(
            analyse((GENEHMIGUNG.chunk_id, "Der Antrag ist ruhend.")), QUELLEN
        )
        assert "nicht wörtlich" in fehler

    def test_zeilenumbrueche_sind_egal(self) -> None:
        beleg = (
            GENEHMIGUNG.chunk_id,
            "Thema: Baugenehmigung   Haus B Sachstand: Der Antrag ruht",
        )
        assert check_sources(analyse(beleg), QUELLEN) == []

    def test_ueberschrift_ist_zitierbar(self) -> None:
        assert (
            check_sources(
                analyse((GENEHMIGUNG.chunk_id, "Tagesordnungspunkte")), QUELLEN
            )
            == []
        )

    def test_leerer_auszug_belegt_nichts(self) -> None:
        assert check_sources(analyse((GENEHMIGUNG.chunk_id, "  ")), QUELLEN)


class TestQuellenformat:
    def test_metadaten_und_text(self) -> None:
        text = format_sources([GENEHMIGUNG])
        assert f'id="{GENEHMIGUNG.chunk_id}"' in text
        assert 'datei="2026-09-15_baubesprechung.docx"' in text
        assert 'stelle="TOP 4"' in text
        assert 'datum="2026-09-15"' in text
        assert "Überschrift: Tagesordnungspunkte" in text
        assert "Der Antrag ruht" in text


class TestAnalyse:
    def test_bericht_mit_aufgeloesten_quellen(self) -> None:
        bericht = analyze(
            [BRANDSCHUTZ, GENEHMIGUNG],
            project_id="BAU-42",
            model=FunctionModel(antwort(risiko(GUTER_BELEG))),
            now=JETZT,
        )
        assert bericht.project_id == "BAU-42"
        assert bericht.created_at == JETZT
        assert [r.title for r in bericht.risks] == ["Baugenehmigung Haus B ruht"]
        # Nur zitierte Chunks landen im Bericht – mit vollständiger Herkunft.
        assert list(bericht.sources) == [GENEHMIGUNG.chunk_id]
        assert (
            bericht.sources[GENEHMIGUNG.chunk_id]
            .citation()
            .startswith("BAU-42 · 2026-09-15")
        )

    def test_modell_sieht_nur_die_quellen(self) -> None:
        gesehen: list[str] = []

        def modell(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            gesehen.append(str(messages[0]))
            return antwort()(messages, info)

        analyze([GENEHMIGUNG], project_id="BAU-42", model=FunctionModel(modell))
        assert GENEHMIGUNG.chunk_id in gesehen[0]
        assert BRANDSCHUTZ.chunk_id not in gesehen[0]

    def test_falscher_beleg_wird_nachgebessert(self) -> None:
        """Erste Antwort mit erfundener Quelle, zweite korrekt: Das Modell bekommt den Fehler zurück."""
        antworten = [risiko(("f" * 32, "Der Antrag ruht")), risiko(GUTER_BELEG)]
        rueckmeldungen: list[str] = []

        def modell(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            letzte = messages[-1]
            if isinstance(letzte, ModelRequest):
                rueckmeldungen.extend(
                    str(p.content)
                    for p in letzte.parts
                    if isinstance(p, RetryPromptPart)
                )
            return antwort(antworten.pop(0))(messages, info)

        bericht = analyze(
            [GENEHMIGUNG], project_id="BAU-42", model=FunctionModel(modell)
        )
        assert list(bericht.sources) == [GENEHMIGUNG.chunk_id]
        assert len(rueckmeldungen) == 1
        assert "nicht geliefert" in rueckmeldungen[0]
        # Die Nachbesserung ist in den Laufdaten sichtbar – Maßstab beim Modellvergleich.
        assert bericht.stats.requests == 2
        assert bericht.stats.retries == 1
        assert bericht.stats.provided_chunks == 1

    def test_dauerhaft_falsche_belege_ergeben_keinen_bericht(self) -> None:
        """TestModel füllt das Schema mit Zufallswerten – also mit erfundenen chunk_ids."""
        with pytest.raises(UnexpectedModelBehavior):
            analyze([GENEHMIGUNG], project_id="BAU-42", model=TestModel())

    def test_ohne_treffer_kein_aufruf(self) -> None:
        def modell(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            raise AssertionError("Das Sprachmodell darf nicht aufgerufen werden.")

        bericht = analyze([], project_id="BAU-42", model=FunctionModel(modell))
        assert bericht.risks == []

    def test_fremde_chunks_werden_abgelehnt(self) -> None:
        with pytest.raises(ValueError, match="BAU-43"):
            analyze([GENEHMIGUNG, FREMD], project_id="BAU-42", model=TestModel())

    def test_ungueltige_projekt_id(self) -> None:
        with pytest.raises(ValueError, match="Ungültige Projekt-ID"):
            analyze([], project_id="../BAU-42", model=TestModel())


@pytest.mark.db
class TestBelegeSammeln:
    def test_nur_eigenes_projekt_ohne_dubletten_chronologisch(
        self, db: psycopg.Connection
    ) -> None:
        alt = chunk(
            "Rohbau Haus A: Verzug 5 Arbeitstage.",
            document=make_document(
                file_name="statusbericht_2026-08.pdf",
                doc_type=DocType.STATUSBERICHT,
                media_type="application/pdf",
                document_date=date(2026, 8, 31),
            ),
        )
        upsert_chunks(
            db,
            [
                (GENEHMIGUNG, basis(0)),
                (alt, basis(1)),
                (
                    chunk(
                        "Baugenehmigung erteilt, Aufzug verzögert.", document=BERICHT_43
                    ),
                    basis(0),
                ),
            ],
        )
        belege = collect_evidence(
            db,
            project_id="BAU-42",
            encoder=FakeEncoder(vectors={"query:": basis(0)}),
            questions=[
                "Welche Genehmigungen fehlen?",
                "Welche Termine sind verzögert?",
            ],
        )
        assert [c.chunk_id for c in belege] == [alt.chunk_id, GENEHMIGUNG.chunk_id]


class TestAusgabemodus:
    """Lokale Modelle füllen das Schema per Grammatik (NativeOutput), andere per Tool-Aufruf."""

    def test_ollama_nutzt_native_ausgabe(self) -> None:
        assert isinstance(output_spec("ollama:qwen3.8:27b-q4_K_M"), NativeOutput)

    def test_andere_anbieter_nutzen_das_modell_direkt(self) -> None:
        assert output_spec("anthropic:claude-opus-5") is RiskAnalysis
        assert output_spec(TestModel()) is RiskAnalysis


class TestMarkdown:
    def bericht(self) -> RiskReport:
        return analyze(
            [BRANDSCHUTZ, GENEHMIGUNG],
            project_id="BAU-42",
            model=FunctionModel(antwort(risiko(GUTER_BELEG))),
            now=JETZT,
        )

    def test_pflichtfelder_und_trennung(self) -> None:
        text = render_markdown(self.bericht())
        assert text.startswith("# Risikobericht BAU-42")
        assert (
            "| 1 | Baugenehmigung Haus B ruht | genehmigung | hoch | hoch | eingetreten |"
            in text
        )
        assert "**Fakten**" in text
        assert "**Schlussfolgerungen** (abgeleitet)" in text
        assert "**Unsicherheiten**" not in text  # leer → Abschnitt entfällt

    def test_quelle_mit_version_und_auszug(self) -> None:
        text = render_markdown(self.bericht())
        assert "- Der Antrag ruht. [1]" in text
        assert (
            f"**[1]** {GENEHMIGUNG.citation()} · Version {GENEHMIGUNG.document_id[:8]}"
            in text
        )
        assert "> „Der Antrag ruht, Prüfbericht fehlt.“" in text

    def test_kopfzeile_mit_laufdaten(self) -> None:
        kopf = render_markdown(self.bericht()).splitlines()[2]
        assert "2 Textstellen ausgewertet, 1 zitiert" in kopf
        assert "0 Nachbesserungen" in kopf

    def test_sortiert_nach_schwere(self) -> None:
        leicht = risiko(GUTER_BELEG) | {"title": "Leicht", "severity": "niedrig"}
        schwer = risiko(GUTER_BELEG) | {"title": "Schwer", "severity": "hoch"}
        bericht = analyze(
            [GENEHMIGUNG],
            project_id="BAU-42",
            model=FunctionModel(antwort(leicht, schwer)),
        )
        text = render_markdown(bericht)
        assert text.index("## 1. Schwer") < text.index("## 2. Leicht")

    def test_mehrere_auszuege_einer_quelle_ein_verweis(self) -> None:
        zwei_auszuege = risiko(
            (GENEHMIGUNG.chunk_id, "Der Antrag ruht"),
            (GENEHMIGUNG.chunk_id, "Prüfbericht fehlt"),
        )
        bericht = analyze(
            [GENEHMIGUNG],
            project_id="BAU-42",
            model=FunctionModel(antwort(zwei_auszuege)),
        )
        text = render_markdown(bericht)
        assert "- Der Antrag ruht. [1]\n" in text
        assert "[1][1]" not in text
        # Im Quellenverzeichnis bleiben beide Auszüge sichtbar.
        assert "> „Der Antrag ruht“" in text
        assert "> „Prüfbericht fehlt“" in text

    def test_tausendertrennzeichen(self) -> None:
        assert thousands(12345) == "12.345"


class TestEinstellungen:
    def test_denkstufen(self) -> None:
        assert parse_thinking("") is None
        assert parse_thinking("aus") is False
        assert parse_thinking("high") == "high"
        with pytest.raises(ValueError, match="Denkstufe"):
            parse_thinking("viel")

    def test_wartezeit_und_denken_gehen_ans_modell(self) -> None:
        gesehen: list[Any] = []

        def modell(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            gesehen.append((info.model_settings, info.model_request_parameters))
            return antwort()(messages, info)

        denkfaehig = FunctionModel(modell, profile=ModelProfile(supports_thinking=True))
        analyze([GENEHMIGUNG], project_id="BAU-42", model=denkfaehig, thinking=False)
        settings, parameters = gesehen[0]
        assert settings is not None
        assert settings["timeout"] == LLM_TIMEOUT
        assert settings["max_tokens"] == LLM_MAX_TOKENS  # sonst 4096 bei Anthropic
        # Pydantic AI reicht „thinking“ als Anfrageparameter weiter, nicht als Einstellung.
        assert parameters.thinking is False

    def test_ollama_bekommt_reasoning_effort(self) -> None:
        """Das Qwen-Profil kennt kein Denken; die einheitliche Einstellung ginge verloren."""
        assert (
            model_settings("ollama:qwen3.8:27b-q4_K_M", False)[
                "openai_reasoning_effort"
            ]
            == "none"
        )
        assert (
            model_settings("ollama:qwen3.8:27b-q4_K_M", "high")[
                "openai_reasoning_effort"
            ]
            == "high"
        )
        assert "openai_reasoning_effort" not in model_settings("ollama:x", None)

    def test_andere_anbieter_bekommen_einheitliche_einstellung(self) -> None:
        settings = model_settings("anthropic:claude-opus-5", "low")
        assert settings.get("thinking") == "low"
        assert "openai_reasoning_effort" not in settings
