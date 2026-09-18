"""Testfragen mit erwarteten Fundstellen – die bekannte Wahrheit für scripts/evaluate_search.py.

Kriterium: Eine Fundstelle ist relevant, wenn sie die Frage selbst beantwortet oder
unmittelbar belegt. Hintergrund, der nur zum Thema gehört, zählt nicht.

Die Fragen sind bewusst unterschiedlich gebaut:

* **Umschreibung** – andere Wörter als im Dokument („noch nicht entschieden“ statt „offen“).
* **Kompositum** – die Frage nutzt einen Wortteil, das Dokument das zusammengesetzte Wort.
* **Exakter Begriff** – Aktenzeichen, Nachtragsnummern, Firmennamen.
* **Kontrolle BAU-43** – dieselben Begriffe im anderen Projekt, mit anderem Sachstand.

Bei Änderungen am Generator (scripts/generate_sample_documents.py) hier nachziehen.
"""

from dataclasses import dataclass

P23 = "2026-09-01_baubesprechung.docx"
P24 = "2026-09-08_baubesprechung.docx"
P25 = "2026-09-15_baubesprechung.docx"
SB08 = "statusbericht_2026-08.pdf"
SB09 = "statusbericht_2026-09.pdf"
BG = "baugenehmigung.pdf"
KORR = "behördenkorrespondenz.pdf"
PLAN = "bauzeitenplan.xlsx"
P43 = "2026-09-10_baubesprechung.docx"


def row(vorgang: str) -> str:
    return f"Bauzeitenplan, Zeile {vorgang}"


@dataclass(frozen=True)
class Case:
    """Eine Frage mit den Fundstellen, die sie finden soll."""

    label: str
    kind: str
    project_id: str
    question: str
    expected: frozenset[tuple[str, str]]  # (Dateiname, Fundstelle)


def case(
    label: str, kind: str, project_id: str, question: str, *expected: tuple[str, str]
) -> Case:
    return Case(label, kind, project_id, question, frozenset(expected))


CASES = [
    # --- die sechs eingebauten Sachverhalte (docs/testdaten.md, S1–S6) ---
    case(
        "S1 Genehmigung offen",
        "Kompositum",
        "BAU-42",
        "Welche Genehmigungen sind offen?",
        (P23, "TOP 2"),
        (P24, "TOP 4"),
        (P25, "TOP 4"),
        (SB09, "S. 1"),
        (SB09, "S. 2"),
        (KORR, "S. 1"),
        (KORR, "S. 3"),
        (BG, "S. 1"),
        (PLAN, row("V07")),
    ),
    case(
        "S2 Fassadenplanung",
        "Umschreibung",
        "BAU-42",
        "Ist die Fassadenplanung verspätet?",
        (P24, "TOP 3"),
        (P25, "TOP 2"),
        (SB09, "S. 1"),
        (SB09, "S. 2"),
        (PLAN, row("V03")),
    ),
    case(
        "S3 Rohbauverzug",
        "Umschreibung",
        "BAU-42",
        "Wie groß ist der Verzug beim Rohbau?",
        (P23, "TOP 1"),
        (P24, "TOP 1"),
        (P25, "TOP 1"),
        (SB08, "S. 1"),
        (SB09, "S. 1"),
        (SB09, "S. 2"),
        (PLAN, row("V02")),
    ),
    case(
        "S4 Nachtrag offen",
        "Umschreibung",
        "BAU-42",
        "Welche Nachträge sind noch nicht entschieden?",
        (P25, "TOP 2"),
        (SB09, "S. 3"),
        (SB09, "S. 4"),
    ),
    case(
        "S5 Brandschutz",
        "Kompositum",
        "BAU-42",
        "Wer ist für die Brandschutzprüfung verantwortlich?",
        (P23, "TOP 2"),
        (P24, "TOP 2"),
        (P25, "TOP 3"),
        (SB09, "S. 1"),
        (SB09, "S. 4"),
        (PLAN, row("V06")),
    ),
    case(
        "S6 Baubeginn",
        "Umschreibung",
        "BAU-42",
        "Ist der Baubeginn gefährdet?",
        (P24, "TOP 4"),
        (P25, "TOP 4"),
        (SB09, "S. 1"),
        (SB09, "S. 2"),
        (PLAN, row("V08")),
    ),
    # --- weitere Fragen an BAU-42 ---
    case(
        "Auflagen",
        "Kompositum",
        "BAU-42",
        "Welche Auflagen macht die Behörde?",
        (BG, "S. 2"),
    ),
    case(
        "Frist Bauaufsicht",
        "Umschreibung",
        "BAU-42",
        "Bis wann müssen die fehlenden Unterlagen bei der Bauaufsicht sein?",
        (KORR, "S. 3"),
        (P25, "TOP 3"),
        (SB09, "S. 2"),
    ),
    case(
        "Fehlende Unterlagen",
        "Umschreibung",
        "BAU-42",
        "Welche Unterlagen fehlen noch für den Bauantrag?",
        (KORR, "S. 1"),
        (KORR, "S. 2"),
        (KORR, "S. 3"),
        (P23, "TOP 2"),
    ),
    case(
        "Dämmung geändert",
        "Kompositum",
        "BAU-42",
        "Warum wurde die Dämmung der Fassade geändert?",
        (P24, "TOP 3"),
        (P25, "TOP 2"),
        (BG, "S. 2"),
        (SB09, "S. 3"),
    ),
    case(
        "Nachtragskosten",
        "Kompositum",
        "BAU-42",
        "Welche Kosten entstehen durch Nachträge?",
        (P23, "TOP 5"),
        (P25, "TOP 2"),
        (SB08, "S. 3"),
        (SB09, "S. 3"),
    ),
    case(
        "Budgetreserve",
        "Kompositum",
        "BAU-42",
        "Wie viel Reserve bleibt im Budget?",
        (SB08, "S. 3"),
        (SB09, "S. 3"),
    ),
    case(
        "Pläne an Metallbauer",
        "Umschreibung",
        "BAU-42",
        "Wann braucht der Metallbauer die Pläne für die Fertigung?",
        (P24, "TOP 3"),
        (SB09, "S. 4"),
        (PLAN, row("V04")),
    ),
    case(
        "Samstagsarbeit",
        "Kompositum",
        "BAU-42",
        "Warum wird am Samstag nicht gearbeitet?",
        (P24, "TOP 1"),
        (SB09, "S. 4"),
    ),
    case(
        "Gesamtstatus",
        "Umschreibung",
        "BAU-42",
        "Wie steht das Projekt insgesamt?",
        (SB08, "S. 1"),
        (SB09, "S. 1"),
    ),
    case(
        "Nachtrag N-07",
        "Exakter Begriff",
        "BAU-42",
        "Nachtrag N-07",
        (P25, "TOP 2"),
        (SB09, "S. 3"),
        (SB09, "S. 4"),
    ),
    case(
        "Aktenzeichen",
        "Exakter Begriff",
        "BAU-42",
        "BA-2026-0587",
        (P23, "TOP 2"),
        (KORR, "S. 1"),
        (KORR, "S. 2"),
        (KORR, "S. 3"),
        (BG, "S. 1"),
    ),
    case(
        "Metallbau Hofer",
        "Exakter Begriff",
        "BAU-42",
        "Metallbau Hofer",
        (P24, "TOP 3"),
        (SB09, "S. 4"),
        (PLAN, row("V04")),
        (PLAN, row("V05")),
    ),
    # --- Kontrollprojekt BAU-43: gleiche Begriffe, anderer Sachstand ---
    case(
        "BAU-43 Genehmigung",
        "Kontrolle",
        "BAU-43",
        "Ist die Baugenehmigung erteilt?",
        (BG, "S. 1"),
        (SB09, "S. 1"),
    ),
    case(
        "BAU-43 Lieferverzug",
        "Kontrolle",
        "BAU-43",
        "Gibt es Verzögerungen bei Lieferungen?",
        (P43, "TOP 4"),
        (SB09, "S. 1"),
        (SB09, "S. 2"),
    ),
]
