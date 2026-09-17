"""CLI: SQL-Abfragen auf den Parquet-Dateien mit DuckDB.

Die Tabellen heißen ``documents``, ``segments`` und ``chunks``.

Beispiele:
    uv run python scripts/query_parquet.py "SELECT project_id, count(*) FROM chunks GROUP BY 1"
    uv run python scripts/query_parquet.py --beispiele
    uv run python scripts/query_parquet.py --datei abfragen.sql
"""

import argparse
from pathlib import Path

import duckdb

from bauprojekt.config import PARQUET_DIR

BEISPIELE: dict[str, str] = {
    "Bestand je Projekt": """
        SELECT project_id, doc_type, count(*) AS dokumente
        FROM documents GROUP BY 1, 2 ORDER BY 1, 2
    """,
    "Offene Punkte suchen (nur BAU-42)": """
        SELECT file_name, locator, document_date, substr(text, 1, 120) AS auszug
        FROM chunks
        WHERE project_id = 'BAU-42'
          AND lower(text) LIKE '%genehmigung%'
          AND (lower(text) LIKE '%offen%' OR lower(text) LIKE '%nicht erteilt%' OR lower(text) LIKE '%ruht%')
        ORDER BY document_date DESC NULLS LAST
    """,
    "Zeitliche Entwicklung eines Themas": """
        SELECT document_date, file_name, locator, substr(text, 1, 160) AS auszug
        FROM chunks
        WHERE project_id = 'BAU-42' AND text LIKE '%Verzug%'
        ORDER BY document_date NULLS FIRST
    """,
    "Verantwortlichkeiten aus Protokollen": """
        SELECT document_date, locator,
               regexp_extract(text, 'Thema: ([^\\n]*)', 1) AS thema,
               regexp_extract(text, 'Verantwortlich: ([^\\n]*)', 1) AS verantwortlich
        FROM chunks
        WHERE project_id = 'BAU-42' AND doc_type = 'protokoll'
        ORDER BY document_date, locator
    """,
    "Ungeklärte Verantwortlichkeiten": """
        SELECT document_date, file_name, locator,
               regexp_extract(text, 'Thema: ([^\\n]*)', 1) AS thema
        FROM chunks
        WHERE project_id = 'BAU-42'
          AND regexp_extract(text, 'Verantwortlich: ([^\\n]*)', 1) IN ('offen', 'ungeklärt', 'nicht benannt')
        ORDER BY document_date
    """,
    "Beträge aus Nachträgen": """
        SELECT DISTINCT file_name, locator,
               regexp_extract(text, '([0-9][0-9.]*) EUR', 1) AS betrag
        FROM chunks
        WHERE project_id = 'BAU-42' AND text LIKE '%EUR%'
        ORDER BY file_name, locator
    """,
    "Projekttrennung prüfen (muss leer sein)": """
        SELECT project_id, file_name FROM chunks
        WHERE project_id = 'BAU-42' AND (text LIKE '%Grundschule%' OR text LIKE '%Hansen Hochbau%')
    """,
    "Chunk-Längen (Verteilung)": """
        SELECT doc_type, count(*) AS chunks,
               min(length(text)) AS kuerzester,
               round(median(length(text))) AS median,
               max(length(text)) AS laengster
        FROM chunks GROUP BY 1 ORDER BY 1
    """,
    "Dokumentversionen": """
        SELECT source_path, count(*) AS versionen, max(ingested_at) AS zuletzt
        FROM documents GROUP BY 1 HAVING count(*) > 1
    """,
    "Volltext im Zusammenhang (Segment statt Chunk)": """
        SELECT d.file_name, s.locator, s.heading, substr(s.text, 1, 200) AS auszug
        FROM segments s JOIN documents d USING (document_id)
        WHERE s.project_id = 'BAU-42' AND s.text LIKE '%Frist%'
    """,
}


def connect(parquet_dir: Path) -> duckdb.DuckDBPyConnection:
    """Verbindung mit Sichten auf die drei Parquet-Dateien."""
    connection = duckdb.connect()
    for name in ("documents", "segments", "chunks"):
        connection.sql(
            f"CREATE VIEW {name} AS SELECT * FROM read_parquet('{parquet_dir / f'{name}.parquet'}')"
        )
    return connection


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("sql", nargs="?", help="SQL-Abfrage")
    parser.add_argument("--datei", type=Path, help="SQL aus einer Datei lesen")
    parser.add_argument(
        "--beispiele", action="store_true", help="Alle Beispielabfragen ausführen"
    )
    parser.add_argument("--parquet-dir", type=Path, default=PARQUET_DIR)
    args = parser.parse_args()

    connection = connect(args.parquet_dir)

    if args.beispiele:
        for titel, sql in BEISPIELE.items():
            print(f"\n=== {titel} ===")
            connection.sql(sql).show(max_rows=20)
        return

    sql = args.datei.read_text() if args.datei else args.sql
    if not sql:
        parser.error("SQL-Abfrage, --datei oder --beispiele angeben")
    connection.sql(sql).show(max_rows=50)


if __name__ == "__main__":
    main()
