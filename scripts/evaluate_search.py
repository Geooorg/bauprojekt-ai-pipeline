"""CLI: Suchqualität gegen die bekannte Wahrheit messen (Fragen in scripts/search_cases.py).

Gemessen wird der **Recall@k**: Welcher Anteil der erwarteten Fundstellen steht unter den
ersten k Treffern? Das ist die Frage, die für Phase 3 zählt – was hier fehlt, bekommt das
Sprachmodell nicht zu sehen. Nicht gemessen werden Reihenfolge innerhalb der k Treffer
und Rauschen; beides zeigt ``--details``.

Verglichen werden Vektorsuche, Volltextsuche und die Kombination – je Frage, je Fragetyp
und im Durchschnitt.

Aufruf: uv run python scripts/evaluate_search.py [--k 10] [--details]
"""

import argparse
from collections import defaultdict

import psycopg
from search_cases import CASES, Case

from bauprojekt.db import connect
from bauprojekt.embeddings import Encoder, embed_query, load_encoder
from bauprojekt.models import Chunk
from bauprojekt.search import search, text_search, vector_search

METHODS = ("Vektor", "Volltext", "Hybrid")


def key(chunk: Chunk) -> tuple[str, str]:
    return (chunk.file_name, chunk.locator)


def recall(found: list[Chunk], expected: frozenset[tuple[str, str]]) -> float:
    return len({key(c) for c in found} & expected) / len(expected)


def run_case(
    connection: psycopg.Connection, encoder: Encoder, c: Case, k: int
) -> dict[str, list[Chunk]]:
    embedding = embed_query(c.question, encoder=encoder)
    by_vector = vector_search(
        connection, project_id=c.project_id, query_embedding=embedding, limit=k
    )
    by_text = text_search(
        connection, project_id=c.project_id, question=c.question, limit=k
    )
    hybrid = search(
        connection,
        project_id=c.project_id,
        question=c.question,
        encoder=encoder,
        limit=k,
    )
    return {
        "Vektor": [chunk for chunk, _ in by_vector],
        "Volltext": [chunk for chunk, _ in by_text],
        "Hybrid": [hit.chunk for hit in hybrid],
    }


def row(label: str, values: list[float]) -> str:
    return f"{label:<24}" + "".join(f"{value:>10.0%}" for value in values)


def evaluate(
    connection: psycopg.Connection, encoder: Encoder, k: int, details: bool
) -> None:
    print(
        f"Recall@{k}: Anteil der erwarteten Fundstellen unter den ersten {k} Treffern\n"
    )
    header = f"{'Frage':<24}" + "".join(f"{m:>10}" for m in METHODS)
    print(header)
    print("-" * len(header))

    by_kind: dict[str, list[list[float]]] = defaultdict(list)
    all_values: list[list[float]] = []

    for c in CASES:
        results = run_case(connection, encoder, c, k)
        values = [recall(results[m], c.expected) for m in METHODS]
        by_kind[c.kind].append(values)
        all_values.append(values)
        print(row(c.label, values))

        if details:
            hybrid = results["Hybrid"]
            missing = sorted(c.expected - {key(ch) for ch in hybrid})
            if missing:
                print(f"    fehlt:      {missing}")
            if any(ch.project_id != c.project_id for ch in hybrid):
                print("    !!! Treffer aus fremdem Projekt")

    print("-" * len(header))
    for kind, kind_values in sorted(by_kind.items()):
        print(row(f"Ø {kind} ({len(kind_values)})", average(kind_values)))
    print("-" * len(header))
    print(row(f"Ø alle ({len(all_values)})", average(all_values)))


def average(values: list[list[float]]) -> list[float]:
    return [sum(column) / len(column) for column in zip(*values, strict=True)]


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument(
        "--details",
        action="store_true",
        help="Fehlende Fundstellen der Hybrid-Suche zeigen",
    )
    args = parser.parse_args()

    encoder = load_encoder()
    with connect() as connection:
        evaluate(connection, encoder, args.k, args.details)


if __name__ == "__main__":
    main()
