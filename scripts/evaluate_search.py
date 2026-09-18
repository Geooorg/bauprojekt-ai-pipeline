"""CLI: Suchqualität gegen die bekannte Wahrheit aus docs/testdaten.md messen.

Für jede Frage sind die Fundstellen hinterlegt, die ein Mensch erwarten würde. Gemessen
wird der **Recall@k**: Welcher Anteil dieser Fundstellen steht unter den ersten k Treffern?
Verglichen werden Vektorsuche, Volltextsuche und die Kombination.

Aufruf: uv run python scripts/evaluate_search.py [--k 5] [--details]
"""

import argparse
from dataclasses import dataclass

import psycopg

from bauprojekt.db import connect
from bauprojekt.embeddings import Encoder, embed_query, load_encoder
from bauprojekt.models import Chunk
from bauprojekt.search import search, text_search, vector_search

P23 = "2026-09-01_baubesprechung.docx"
P24 = "2026-09-08_baubesprechung.docx"
P25 = "2026-09-15_baubesprechung.docx"
SB08 = "statusbericht_2026-08.pdf"
SB09 = "statusbericht_2026-09.pdf"
BG = "baugenehmigung.pdf"
KORR = "behördenkorrespondenz.pdf"
PLAN = "bauzeitenplan.xlsx"


@dataclass(frozen=True)
class Case:
    """Eine Frage mit den Fundstellen, die sie finden soll."""

    label: str
    project_id: str
    question: str
    expected: frozenset[tuple[str, str]]  # (Dateiname, Fundstelle)


def case(
    label: str, project_id: str, question: str, *expected: tuple[str, str]
) -> Case:
    return Case(label, project_id, question, frozenset(expected))


CASES = [
    case(
        "S1 Genehmigung offen",
        "BAU-42",
        "Welche Genehmigungen sind offen?",
        (P24, "TOP 4"),
        (SB09, "S. 1"),
        (SB09, "S. 2"),
        (KORR, "S. 1"),
        (KORR, "S. 3"),
        (BG, "S. 1"),
        (PLAN, "Bauzeitenplan, Zeile V07"),
    ),
    case(
        "S2 Fassadenplanung",
        "BAU-42",
        "Ist die Fassadenplanung verspätet?",
        (P24, "TOP 3"),
        (P25, "TOP 2"),
        (SB09, "S. 2"),
        (PLAN, "Bauzeitenplan, Zeile V03"),
    ),
    case(
        "S3 Rohbauverzug",
        "BAU-42",
        "Wie groß ist der Verzug beim Rohbau?",
        (P23, "TOP 1"),
        (P24, "TOP 1"),
        (P25, "TOP 1"),
        (SB08, "S. 1"),
        (SB09, "S. 2"),
        (PLAN, "Bauzeitenplan, Zeile V02"),
    ),
    case(
        "S4 Nachtrag offen",
        "BAU-42",
        "Welche Nachträge sind noch nicht entschieden?",
        (P25, "TOP 2"),
        (SB09, "S. 3"),
        (SB09, "S. 4"),
    ),
    case(
        "S5 Brandschutz",
        "BAU-42",
        "Wer ist für die Brandschutzprüfung verantwortlich?",
        (P23, "TOP 2"),
        (P24, "TOP 2"),
        (P25, "TOP 3"),
        (SB09, "S. 1"),
        (SB09, "S. 4"),
        (PLAN, "Bauzeitenplan, Zeile V06"),
    ),
    case(
        "S6 Baubeginn",
        "BAU-42",
        "Ist der Baubeginn gefährdet?",
        (P25, "TOP 4"),
        (SB09, "S. 1"),
        (SB09, "S. 2"),
        (PLAN, "Bauzeitenplan, Zeile V08"),
    ),
    case(
        "Exakter Begriff",
        "BAU-42",
        "Nachtrag N-07",
        (P25, "TOP 2"),
        (SB09, "S. 3"),
    ),
    case(
        "Kontrolle BAU-43",
        "BAU-43",
        "Ist die Baugenehmigung erteilt?",
        (BG, "S. 1"),
        (SB09, "S. 1"),
    ),
]


def key(chunk: Chunk) -> tuple[str, str]:
    return (chunk.file_name, chunk.locator)


def recall(found: list[Chunk], expected: frozenset[tuple[str, str]]) -> float:
    return len({key(c) for c in found} & expected) / len(expected)


def evaluate(
    connection: psycopg.Connection, encoder: Encoder, k: int, details: bool
) -> None:
    print(
        f"Recall@{k}: Anteil der erwarteten Fundstellen unter den ersten {k} Treffern\n"
    )
    print(f"{'Frage':<22} {'Vektor':>7} {'Volltext':>9} {'Hybrid':>7}")
    totals = [0.0, 0.0, 0.0]

    for c in CASES:
        embedding = embed_query(c.question, encoder=encoder)
        by_vector = [
            ch
            for ch, _ in vector_search(
                connection, project_id=c.project_id, query_embedding=embedding, limit=k
            )
        ]
        by_text = [
            ch
            for ch, _ in text_search(
                connection, project_id=c.project_id, question=c.question, limit=k
            )
        ]
        hybrid = [
            h.chunk
            for h in search(
                connection,
                project_id=c.project_id,
                question=c.question,
                encoder=encoder,
                limit=k,
            )
        ]

        values = [
            recall(by_vector, c.expected),
            recall(by_text, c.expected),
            recall(hybrid, c.expected),
        ]
        totals = [t + v for t, v in zip(totals, values, strict=True)]
        print(f"{c.label:<22} {values[0]:>7.0%} {values[1]:>9.0%} {values[2]:>7.0%}")

        if details:
            missing = sorted(c.expected - {key(ch) for ch in hybrid})
            extra = [key(ch) for ch in hybrid if key(ch) not in c.expected]
            if missing:
                print(f"   fehlt:      {missing}")
            if extra:
                print(f"   zusätzlich: {extra}")
            if any(ch.project_id != c.project_id for ch in hybrid):
                print("   !!! Treffer aus fremdem Projekt")

    n = len(CASES)
    print(
        f"{'Durchschnitt':<22} {totals[0] / n:>7.0%} {totals[1] / n:>9.0%} {totals[2] / n:>7.0%}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument(
        "--details",
        action="store_true",
        help="Fehlende und zusätzliche Fundstellen zeigen",
    )
    args = parser.parse_args()

    encoder = load_encoder()
    with connect() as connection:
        evaluate(connection, encoder, args.k, args.details)


if __name__ == "__main__":
    main()
