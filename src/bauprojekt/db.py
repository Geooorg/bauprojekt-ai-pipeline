"""PostgreSQL mit pgvector: Schema und Schreibzugriff.

Eine Tabelle ``chunks``. Die Herkunftsfelder stehen redundant darin, wie im Chunk-Modell
– dadurch genügt für die Projekttrennung ein ``WHERE project_id = …`` ohne Join, und ein
Treffer ist allein zitierfähig.

``text_search`` ist eine berechnete Spalte: Postgres pflegt sie selbst fort und stemmt mit
der deutschen Konfiguration. Damit findet „Fristen“ auch „Frist“. Zusammen mit der
Vektorsuche ergibt das die Hybrid-Suche in ``search.py``.

Kein Vektorindex: Bei einigen tausend Chunks ist die vollständige Suche exakt und schnell
genug. Ein HNSW-Index liefert nur Näherungen und lohnt sich erst bei deutlich mehr Daten.
"""

from collections.abc import Sequence

import psycopg
from pgvector.psycopg import register_vector

from bauprojekt.config import DATABASE_URL, EMBEDDING_DIM, TEXT_SEARCH_CONFIG
from bauprojekt.models import Chunk

Embedding = Sequence[float]

COLUMNS = (
    "chunk_id",
    "segment_id",
    "document_id",
    "project_id",
    "index",
    "text",
    "char_start",
    "char_end",
    "source_path",
    "file_name",
    "doc_type",
    "document_date",
    "page_no",
    "locator",
    "heading",
    "embedding",
)


def connect(url: str = DATABASE_URL) -> psycopg.Connection:
    """Verbindung öffnen und pgvector-Typen registrieren."""
    connection = psycopg.connect(url, autocommit=True)
    register_vector(connection)
    return connection


def init_schema(connection: psycopg.Connection) -> None:
    """Tabelle und Indizes anlegen. Mehrfaches Aufrufen ist unschädlich."""
    connection.execute("CREATE EXTENSION IF NOT EXISTS vector")
    register_vector(connection)
    connection.execute(f"""
        CREATE TABLE IF NOT EXISTS chunks (
            chunk_id      text PRIMARY KEY,
            segment_id    text NOT NULL,
            document_id   text NOT NULL,
            project_id    text NOT NULL,
            index         integer NOT NULL,
            text          text NOT NULL,
            char_start    integer NOT NULL,
            char_end      integer NOT NULL,
            source_path   text NOT NULL,
            file_name     text NOT NULL,
            doc_type      text NOT NULL,
            document_date date,
            page_no       integer,
            locator       text NOT NULL,
            heading       text,
            embedding     vector({EMBEDDING_DIM}),
            text_search   tsvector GENERATED ALWAYS AS (
                to_tsvector('{TEXT_SEARCH_CONFIG}', coalesce(heading, '') || ' ' || text)
            ) STORED
        )
    """)
    connection.execute(
        "CREATE INDEX IF NOT EXISTS chunks_project_idx ON chunks (project_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS chunks_document_idx ON chunks (document_id)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS chunks_search_idx ON chunks USING gin (text_search)"
    )


def upsert_chunks(
    connection: psycopg.Connection, items: Sequence[tuple[Chunk, Embedding]]
) -> int:
    """Chunks mit ihren Embeddings schreiben, vorhandene aktualisieren.

    Die ``chunk_id`` ist aus dem Inhalt abgeleitet und damit über Läufe hinweg stabil.
    Ein erneuter Lauf überschreibt deshalb denselben Datensatz, statt Dubletten anzulegen.
    """
    if not items:
        return 0

    updates = ", ".join(
        f"{column} = EXCLUDED.{column}" for column in COLUMNS if column != "chunk_id"
    )
    statement = (
        f"INSERT INTO chunks ({', '.join(COLUMNS)}) VALUES ({', '.join(['%s'] * len(COLUMNS))})"
        f" ON CONFLICT (chunk_id) DO UPDATE SET {updates}"
    )
    rows = [
        (
            chunk.chunk_id,
            chunk.segment_id,
            chunk.document_id,
            chunk.project_id,
            chunk.index,
            chunk.text,
            chunk.char_start,
            chunk.char_end,
            chunk.source_path,
            chunk.file_name,
            str(chunk.doc_type),
            chunk.document_date,
            chunk.page_no,
            chunk.locator,
            chunk.heading,
            list(embedding),
        )
        for chunk, embedding in items
    ]
    with connection.cursor() as cursor:
        cursor.executemany(statement, rows)
    return len(rows)


def fetch_known_chunk_ids(
    connection: psycopg.Connection, *, project_id: str | None = None
) -> set[str]:
    """Bereits gespeicherte Chunk-IDs – Grundlage dafür, nur Neues einzubetten."""
    if project_id is None:
        result = connection.execute("SELECT chunk_id FROM chunks")
    else:
        result = connection.execute(
            "SELECT chunk_id FROM chunks WHERE project_id = %s", (project_id,)
        )
    return {row[0] for row in result.fetchall()}
