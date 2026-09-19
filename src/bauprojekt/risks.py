"""Risikomodell: das Ausgabeschema, das das Sprachmodell füllt.

Die Feldbeschreibungen (``description``) sind nicht nur Dokumentation: Pydantic AI
übersetzt die Modelle in ein JSON-Schema, und das Sprachmodell liest genau diese Texte.
Sie sind damit Teil des Prompts.

Drei Ebenen einer Aussage werden getrennt gehalten (Leitplanke der Produktvision):

* **Fakten** stehen so in einem Dokument und tragen mindestens einen Beleg.
* **Schlussfolgerungen** leitet das Modell aus mehreren Fakten ab – etwa eine
  Ursachenkette, die in keinem einzelnen Dokument steht.
* **Unsicherheiten** benennen, was offen, widersprüchlich oder nur eine Einschätzung ist.

Ein Beleg besteht aus ``chunk_id`` und wörtlichem Auszug. Beides ist maschinell prüfbar
(siehe ``report.check_sources``): Die ID muss aus den gelieferten Suchtreffern stammen,
der Auszug muss in genau diesem Chunk stehen. Ein erfundener Beleg fällt so auf, bevor er
in einem Bericht landet.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from bauprojekt.models import Chunk, ProjectId


class RiskCategory(StrEnum):
    TERMIN = "termin"
    KOSTEN = "kosten"
    GENEHMIGUNG = "genehmigung"
    PLANUNG = "planung"
    QUALITAET = "qualität"
    VERTRAG = "vertrag"
    RESSOURCEN = "ressourcen"
    LIEFERANTEN = "lieferanten"
    SCHNITTSTELLEN = "schnittstellen"


class Level(StrEnum):
    """Dreistufig statt Prozent: Eine Zahl wie „70 %“ täte eine Genauigkeit vor, die das
    Modell aus Protokollen nicht ableiten kann."""

    NIEDRIG = "niedrig"
    MITTEL = "mittel"
    HOCH = "hoch"


class RiskStatus(StrEnum):
    OFFEN = "offen"
    """Kann eintreten, ist es aber noch nicht."""
    EINGETRETEN = "eingetreten"
    """Ist bereits eingetreten (z. B. ein bestehender Verzug) und wirkt weiter."""
    IN_BEARBEITUNG = "in_bearbeitung"
    """Eine Maßnahme läuft nachweislich."""


class _Strict(BaseModel):
    # extra="forbid" wird im JSON-Schema zu additionalProperties: false – das Modell
    # darf keine eigenen Felder erfinden.
    model_config = ConfigDict(frozen=True, extra="forbid")


class Evidence(_Strict):
    """Ein Quellenbeleg: welche Textstelle, und was genau dort steht."""

    chunk_id: str = Field(
        description="ID der Quelle, exakt wie im Attribut id der gelieferten <quelle>."
    )
    excerpt: str = Field(
        description=(
            "Wörtlicher Auszug aus genau dieser Quelle, ein bis zwei Sätze, ohne Änderung "
            "und ohne Auslassungszeichen. Wird maschinell gegen den Quelltext geprüft."
        )
    )


class Fact(_Strict):
    """Eine Aussage, die so in den Dokumenten steht."""

    statement: str = Field(description="Die Tatsache, knapp formuliert.")
    evidence: list[Evidence] = Field(
        min_length=1, description="Mindestens ein Beleg; ohne Beleg kein Fakt."
    )


class Risk(_Strict):
    """Ein Risiko mit den Pflichtfeldern der Produktvision."""

    title: str = Field(description="Kurzer, eindeutiger Titel.")
    category: RiskCategory
    description: str = Field(
        description="Worin das Risiko besteht, in zwei bis vier Sätzen."
    )
    project_area: str = Field(
        description="Betroffener Projektbereich, z. B. 'Haus B', 'Fassade', 'Rohbau Haus A'."
    )
    impact: str = Field(
        description="Mögliche Auswirkung, wenn das Risiko eintritt oder anhält."
    )
    probability: Level = Field(
        description="Wahrscheinlichkeit des Eintretens bzw. Andauerns."
    )
    severity: Level = Field(description="Schweregrad der Auswirkung.")
    owner: str = Field(
        description=(
            "Verantwortliche Stelle laut Dokumenten. 'nicht benannt', wenn die Dokumente "
            "keine nennen – nicht raten."
        )
    )
    measure: str = Field(description="Empfohlene Maßnahme, konkret und umsetzbar.")
    status: RiskStatus
    facts: list[Fact] = Field(
        min_length=1, description="Belegte Tatsachen, auf denen das Risiko beruht."
    )
    conclusions: list[str] = Field(
        default_factory=list,
        description=(
            "Eigene Schlussfolgerungen aus mehreren Fakten, z. B. Ursachenketten oder "
            "Terminfolgen, die so in keinem Dokument stehen."
        ),
    )
    uncertainties: list[str] = Field(
        default_factory=list,
        description=(
            "Was offen, widersprüchlich oder nur Einschätzung ist (z. B. 'nicht bestätigte "
            "Schätzung laut Protokoll')."
        ),
    )


class RiskAnalysis(_Strict):
    """Das, was das Sprachmodell liefert."""

    risks: list[Risk] = Field(
        description="Alle belegbaren Risiken, das schwerwiegendste zuerst. Erledigte Punkte sind keine Risiken."
    )


class RunStats(BaseModel):
    """Was der Lauf gekostet hat – Grundlage für den Vergleich von Modellen."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provided_chunks: int = Field(description="An das Modell gelieferte Chunks")
    requests: int = Field(
        description="Anfragen an das Modell, Nachbesserungen eingeschlossen"
    )
    retries: int = Field(
        description="Nachbesserungen wegen ungültiger Belege oder Schemafehler"
    )
    input_tokens: int
    output_tokens: int
    seconds: float


class RiskReport(BaseModel):
    """Der fertige Bericht: Analyse plus die aufgelösten Quellen.

    ``project_id``, Zeitpunkt, Modell und Quellen setzt der Code, nicht das Sprachmodell –
    was maschinell bekannt ist, soll das Modell weder erzeugen noch verfälschen können.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_id: ProjectId
    created_at: datetime
    model_name: str
    stats: RunStats
    risks: list[Risk]
    sources: dict[str, Chunk] = Field(
        description="Zitierte Chunks nach chunk_id: Datei, Version, Stelle, Datum, Text."
    )
