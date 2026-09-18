"""CLI: Hybrid-Suche in einem Projekt.

Aufruf:
    uv run python scripts/search_documents.py BAU-42 "Welche Genehmigungen sind offen?"
    uv run python scripts/search_documents.py BAU-42 "Nachtrag N-07" --limit 3 --volltext
"""

import argparse
import textwrap

from bauprojekt.db import connect
from bauprojekt.embeddings import load_encoder
from bauprojekt.search import SearchHit, search


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "project",
        help="Projekt-ID, z. B. BAU-42 (Pflicht: keine projektübergreifende Suche)",
    )
    parser.add_argument("question", help="Frage in natürlicher Sprache")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument(
        "--volltext", action="store_true", help="Ganzen Chunk-Text zeigen"
    )
    args = parser.parse_args()

    encoder = load_encoder()
    with connect() as connection:
        hits = search(
            connection,
            project_id=args.project,
            question=args.question,
            encoder=encoder,
            limit=args.limit,
        )

    if not hits:
        print(f"Keine Treffer in {args.project}.")
        return
    for number, hit in enumerate(hits, start=1):
        print_hit(number, hit, full_text=args.volltext)


def print_hit(number: int, hit: SearchHit, *, full_text: bool) -> None:
    ranks = f"Vektor {hit.vector_rank or '–'} · Volltext {hit.text_rank or '–'}"
    print(f"\n{number}. {hit.chunk.citation()}")
    print(f"   Punkte {hit.score:.4f} ({ranks})")
    text = (
        hit.chunk.text
        if full_text
        else textwrap.shorten(hit.chunk.text, 220, placeholder=" …")
    )
    print(textwrap.indent(textwrap.fill(text, 96) if not full_text else text, "   │ "))


if __name__ == "__main__":
    main()
