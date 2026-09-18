"""CLI: Chunks aus Parquet einbetten und nach PostgreSQL schreiben.

Nur Chunks, die noch nicht in der Datenbank stehen, werden eingebettet.
Voraussetzung: laufende Datenbank und eingelesene Dokumente (scripts/ingest_documents.py).

Aufruf: uv run python scripts/embed_chunks.py [--project BAU-42]
"""

import argparse
import time
from pathlib import Path

from bauprojekt.config import EMBEDDING_MODEL, PARQUET_DIR
from bauprojekt.db import connect, init_schema
from bauprojekt.embeddings import load_encoder
from bauprojekt.pipeline import index_chunks


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--project", default=None, help="Nur dieses Projekt, z. B. BAU-42"
    )
    parser.add_argument("--parquet-dir", type=Path, default=PARQUET_DIR)
    args = parser.parse_args()

    started = time.perf_counter()
    print(f"Lade Modell {EMBEDDING_MODEL} …")
    encoder = load_encoder()

    with connect() as connection:
        init_schema(connection)
        result = index_chunks(
            connection=connection,
            encoder=encoder,
            parquet_dir=args.parquet_dir,
            project_id=args.project,
        )

    print(
        f"{result.embedded} Chunks eingebettet, {result.skipped} übersprungen "
        f"(bereits in der Datenbank) – {time.perf_counter() - started:.1f} s."
    )


if __name__ == "__main__":
    main()
