"""CLI: Risikobericht für ein Projekt erzeugen.

Sucht Belege je Risikokategorie, lässt das Sprachmodell die Risiken ableiten, prüft jeden
Beleg und schreibt zwei Dateien nach data/generated/<PROJEKT>/:

* ``…md``   – der Bericht zum Lesen
* ``…json`` – derselbe Bericht als Daten, für scripts/evaluate_report.py. Einmal erzeugt,
  lässt er sich beliebig oft neu bewerten, ohne das Modell erneut aufzurufen.

Aufruf:
    uv run python scripts/create_report.py BAU-42
    uv run python scripts/create_report.py BAU-42 --modell ollama:qwen3.8:27b-q4_K_M

Anthropic braucht ANTHROPIC_API_KEY, Ollama braucht OLLAMA_BASE_URL (siehe README).
"""

import argparse
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

from pydantic_ai import UnexpectedModelBehavior

from bauprojekt.config import GENERATED_DIR, LLM_MODEL
from bauprojekt.db import connect
from bauprojekt.embeddings import load_encoder
from bauprojekt.models import validate_project_id
from bauprojekt.report import create_report
from bauprojekt.report_markdown import render_markdown


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("project", help="Projekt-ID, z. B. BAU-42")
    parser.add_argument(
        "--modell",
        default=LLM_MODEL,
        help=f"Sprachmodell als anbieter:modell (Vorgabe: {LLM_MODEL})",
    )
    parser.add_argument(
        "--ausgabe",
        type=Path,
        default=GENERATED_DIR,
        help="Zielordner; darin je Projekt ein Unterordner",
    )
    args = parser.parse_args()
    project_id = validate_project_id(args.project)

    print(f"Risikobericht für {project_id} mit {args.modell} …", flush=True)
    encoder = load_encoder()
    started = datetime.now(UTC)
    try:
        with connect() as connection:
            report = create_report(
                connection, project_id=project_id, encoder=encoder, model=args.modell
            )
    except UnexpectedModelBehavior as error:
        # Das Modell hat auch nach allen Nachbesserungen ungültige Belege geliefert.
        print(f"Abgebrochen, kein Bericht: {error}", file=sys.stderr)
        sys.exit(1)

    target = args.ausgabe / project_id
    target.mkdir(parents=True, exist_ok=True)
    stem = f"risikobericht_{started:%Y%m%d-%H%M}_{slug(args.modell)}"
    markdown = target / f"{stem}.md"
    data = target / f"{stem}.json"
    markdown.write_text(render_markdown(report), encoding="utf-8")
    data.write_text(report.model_dump_json(indent=2), encoding="utf-8")

    stats = report.stats
    print(
        f"{len(report.risks)} Risiken · {stats.provided_chunks} Textstellen ausgewertet, "
        f"{len(report.sources)} zitiert · {stats.retries} Nachbesserungen · "
        f"{stats.input_tokens} / {stats.output_tokens} Tokens · {stats.seconds:.0f} s"
    )
    print(f"Bericht: {markdown}\nDaten:   {data}")


def slug(model: str) -> str:
    """'ollama:qwen3.8:27b-q4_K_M' → 'ollama-qwen3.8-27b-q4_K_M' (für Dateinamen)."""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", model).strip("-")


if __name__ == "__main__":
    main()
