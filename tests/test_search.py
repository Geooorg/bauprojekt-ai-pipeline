"""Tests für bauprojekt.search.

Die Vektoren sind von Hand gesetzt (Einheitsvektoren), damit die Reihenfolge der Treffer
vorhersagbar ist. Ob das echte Modell gute Treffer liefert, prüft die Auswertung gegen
docs/testdaten.md – nicht dieser Test.
"""

import psycopg
import pytest
from conftest import FakeEncoder, basis, make_document

from bauprojekt.db import upsert_chunks
from bauprojekt.models import Chunk, DocType, Document, Segment, SegmentKind
from bauprojekt.search import (
    reciprocal_rank_fusion,
    search,
    text_search,
    vector_search,
)

BAU42 = make_document(
    file_name="2026-09-15_baubesprechung.docx",
    doc_type=DocType.PROTOKOLL,
    media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
)
BAU43 = make_document(
    file_name="2026-09-10_baubesprechung.docx",
    doc_type=DocType.PROTOKOLL,
    media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    project_id="BAU-43",
)


def chunk(text: str, *, index: int, document: Document = BAU42) -> Chunk:
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


GENEHMIGUNG = chunk(
    "Die Baugenehmigung für Haus B ist nicht erteilt, der Antrag ruht.", index=0
)
BRANDSCHUTZ = chunk(
    "Für die Brandschutzprüfung ist kein Verantwortlicher benannt.", index=1
)
ROHBAU = chunk("Der Rohbau liegt zwei Wochen im Verzug.", index=2)
GENEHMIGUNG_43 = chunk(
    "Die Baugenehmigung ist vollständig erteilt.", index=0, document=BAU43
)


@pytest.fixture
def befuellt(db: psycopg.Connection) -> psycopg.Connection:
    """Drei Chunks in BAU-42 auf drei orthogonalen Achsen, ein Gegenstück in BAU-43."""
    upsert_chunks(
        db,
        [
            (GENEHMIGUNG, basis(0)),
            (BRANDSCHUTZ, basis(1)),
            (ROHBAU, basis(2)),
            (
                GENEHMIGUNG_43,
                basis(0),
            ),  # gleicher Vektor wie GENEHMIGUNG – Falle für die Trennung
        ],
    )
    return db


def encoder_fuer(achse: int) -> FakeEncoder:
    """Ein Encoder, der jede Frage auf dieselbe Achse legt."""
    return FakeEncoder(vectors={"query: ": basis(achse)})


class TestRangfusion:
    """Reciprocal Rank Fusion: Punkte je Liste 1 / (k + Rang), dann addiert."""

    def test_in_beiden_listen_schlaegt_eine_liste(self) -> None:
        punkte = reciprocal_rank_fusion([["a", "b"], ["b", "c"]], k=60)
        assert max(punkte, key=punkte.__getitem__) == "b"

    def test_rang_zaehlt_nicht_der_rohwert(self) -> None:
        """Deshalb lassen sich Cosinus-Ähnlichkeit und Textrang überhaupt verbinden."""
        punkte = reciprocal_rank_fusion([["a"]], k=60)
        assert punkte["a"] == pytest.approx(1 / 61)

    def test_leere_listen(self) -> None:
        assert reciprocal_rank_fusion([[], []]) == {}


@pytest.mark.db
class TestVektorsuche:
    def test_naechster_vektor_zuerst(self, befuellt: psycopg.Connection) -> None:
        treffer = vector_search(
            befuellt, project_id="BAU-42", query_embedding=basis(1), limit=3
        )
        assert treffer[0][0].chunk_id == BRANDSCHUTZ.chunk_id
        assert treffer[0][1] == pytest.approx(
            1.0
        )  # Cosinus-Ähnlichkeit, identischer Vektor

    def test_liefert_zitierfaehige_chunks(self, befuellt: psycopg.Connection) -> None:
        treffer, _ = vector_search(
            befuellt, project_id="BAU-42", query_embedding=basis(0), limit=1
        )[0]
        assert (
            treffer.citation()
            == "BAU-42 · 2026-09-15_baubesprechung.docx · TOP 1 · 15.09.2026"
        )


@pytest.mark.db
class TestVolltextsuche:
    def test_findet_gebeugte_form(self, befuellt: psycopg.Connection) -> None:
        treffer = text_search(
            befuellt, project_id="BAU-42", question="Verantwortliche", limit=5
        )
        assert [c.chunk_id for c, _ in treffer] == [BRANDSCHUTZ.chunk_id]

    def test_ein_passendes_wort_genuegt(self, befuellt: psycopg.Connection) -> None:
        """Wörter werden mit ODER verknüpft. Mit UND müsste jedes Wort der Frage vorkommen –
        'offen' steht aber nirgends, und die Suche fände nichts."""
        treffer = text_search(
            befuellt, project_id="BAU-42", question="Ist der Antrag offen?", limit=5
        )
        assert [c.chunk_id for c, _ in treffer] == [GENEHMIGUNG.chunk_id]

    def test_zerlegt_keine_zusammengesetzten_woerter(
        self, befuellt: psycopg.Connection
    ) -> None:
        """Bekannte Grenze: 'Genehmigungen' → 'genehm', 'Baugenehmigung' → 'baugenehm'.

        Postgres stemmt, zerlegt aber keine Komposita. Dieser Test dokumentiert die Lücke,
        die in der Hybrid-Suche die Vektorsuche schließt (siehe TestHybrid).
        """
        treffer = text_search(
            befuellt, project_id="BAU-42", question="Genehmigungen", limit=5
        )
        assert treffer == []

    def test_nur_fuellwoerter_ergibt_nichts(self, befuellt: psycopg.Connection) -> None:
        assert (
            text_search(befuellt, project_id="BAU-42", question="und die oder", limit=5)
            == []
        )


@pytest.mark.db
class TestHybrid:
    def test_liefert_treffer_mit_quelle_und_raengen(
        self, befuellt: psycopg.Connection
    ) -> None:
        treffer = search(
            befuellt,
            project_id="BAU-42",
            question="Brandschutzprüfung",
            encoder=encoder_fuer(1),
        )
        erster = treffer[0]
        assert erster.chunk.chunk_id == BRANDSCHUTZ.chunk_id
        assert erster.vector_rank == 1
        assert erster.text_rank == 1

    def test_volltext_rettet_was_der_vektor_verfehlt(
        self, befuellt: psycopg.Connection
    ) -> None:
        """Vektor zeigt auf Rohbau, das Wort 'Baugenehmigung' auf den Genehmigungs-Chunk.

        Beide Verfahren liefern einen Kandidaten – die Fusion behält beide.
        """
        treffer = search(
            befuellt,
            project_id="BAU-42",
            question="Baugenehmigung",
            encoder=encoder_fuer(2),
        )
        ids = [t.chunk.chunk_id for t in treffer]
        assert GENEHMIGUNG.chunk_id in ids
        assert ROHBAU.chunk_id in ids

    def test_vektor_schliesst_die_luecke_der_komposita(
        self, befuellt: psycopg.Connection
    ) -> None:
        """Der Volltext findet 'Baugenehmigung' über 'Genehmigungen' nicht – die Bedeutung schon."""
        treffer = search(
            befuellt,
            project_id="BAU-42",
            question="Welche Genehmigungen sind offen?",
            encoder=encoder_fuer(0),
        )
        assert treffer[0].chunk.chunk_id == GENEHMIGUNG.chunk_id
        assert treffer[0].text_rank is None
        assert treffer[0].vector_rank == 1

    def test_limit_wird_eingehalten(self, befuellt: psycopg.Connection) -> None:
        treffer = search(
            befuellt,
            project_id="BAU-42",
            question="Rohbau",
            encoder=encoder_fuer(2),
            limit=1,
        )
        assert len(treffer) == 1


@pytest.mark.db
class TestProjekttrennung:
    """Die wichtigste Zusicherung der Suche: nichts aus einem anderen Projekt."""

    def test_gleicher_vektor_anderes_projekt_bleibt_draussen(
        self, befuellt: psycopg.Connection
    ) -> None:
        treffer = search(
            befuellt,
            project_id="BAU-42",
            question="Baugenehmigung erteilt",
            encoder=encoder_fuer(0),
        )
        assert {t.chunk.project_id for t in treffer} == {"BAU-42"}
        assert GENEHMIGUNG_43.chunk_id not in [t.chunk.chunk_id for t in treffer]

    def test_anderes_projekt_findet_nur_seins(
        self, befuellt: psycopg.Connection
    ) -> None:
        treffer = search(
            befuellt,
            project_id="BAU-43",
            question="Baugenehmigung",
            encoder=encoder_fuer(0),
        )
        assert [t.chunk.chunk_id for t in treffer] == [GENEHMIGUNG_43.chunk_id]

    def test_unbekanntes_projekt_liefert_nichts(
        self, befuellt: psycopg.Connection
    ) -> None:
        assert (
            search(
                befuellt,
                project_id="BAU-99",
                question="Baugenehmigung",
                encoder=encoder_fuer(0),
            )
            == []
        )
