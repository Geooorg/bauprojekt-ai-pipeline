"""CLI: Dokumente aus data/raw/ einlesen und als Parquet speichern.

Aufruf: uv run python scripts/ingest_documents.py [--project BAU-42]
"""

import argparse
from pathlib import Path

from bauprojekt.config import PARQUET_DIR, RAW_DIR
from bauprojekt.pipeline import ingest


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--project", default=None, help="Nur dieses Projekt, z. B. BAU-42"
    )
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    parser.add_argument("--parquet-dir", type=Path, default=PARQUET_DIR)
    args = parser.parse_args()

    result = ingest(
        raw_dir=args.raw_dir, parquet_dir=args.parquet_dir, project_id=args.project
    )

    print(
        f"{result.documents} Dokumente verarbeitet, {result.skipped} übersprungen "
        f"(bereits bekannt), {result.segments} Segmente, {result.chunks} Chunks."
    )
    print(f"Geschrieben nach {args.parquet_dir}")
    if result.rejected:
        print(
            f"\nAbgewiesen – nicht in einem Projektordner wie data/raw/BAU-42/…"
            f" ({len(result.rejected)}):"
        )
        for path in result.rejected:
            print(f"  {path}")


if __name__ == "__main__":
    main()
