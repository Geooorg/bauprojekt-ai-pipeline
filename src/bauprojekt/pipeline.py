"""Orchestrierung: Originale lesen, hashen, bekannte Versionen überspringen, Parquet schreiben.

Hier – und nur hier – wird auf das Dateisystem zugegriffen. Extraktion und Chunking bleiben
reine Funktionen. Für den späteren Betrieb im Cluster ist damit genau dieses Modul die
Stelle, die auf Objektspeicher umgestellt werden muss.

Inkrementell über den Inhalts-Hash: Ein Dokument, dessen ``document_id`` schon in
``documents.parquet`` steht, wird übersprungen. Geänderter Inhalt ergibt eine neue ID und
damit eine zusätzliche Version; die alte bleibt erhalten.
"""

import mimetypes
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl

from bauprojekt.chunking import chunk_segments
from bauprojekt.config import PARQUET_DIR, RAW_DIR
from bauprojekt.extraction import extract
from bauprojekt.models import SCHEMAS, Chunk, DocType, Document, Segment, to_frame

SUPPORTED_SUFFIXES = frozenset({".pdf", ".docx", ".xlsx"})

DOC_TYPE_BY_FOLDER = {
    "protokolle": DocType.PROTOKOLL,
    "statusberichte": DocType.STATUSBERICHT,
    "terminplan": DocType.TERMINPLAN,
    "terminplaene": DocType.TERMINPLAN,
    "genehmigungen": DocType.GENEHMIGUNG,
}
"""Ordnername bestimmt die Dokumentart. Reicht für den Prototyp; später ggf. eine Klassifikation."""

DATE_PATTERN = re.compile(r"(?P<year>20\d{2})-(?P<month>\d{2})(?:-(?P<day>\d{2}))?")

TABLES: dict[str, type[Document | Segment | Chunk]] = {
    "documents": Document,
    "segments": Segment,
    "chunks": Chunk,
}


@dataclass(frozen=True)
class IngestResult:
    """Was ein Durchlauf bewirkt hat."""

    documents: int
    skipped: int
    segments: int
    chunks: int


def ingest(
    *,
    raw_dir: Path = RAW_DIR,
    parquet_dir: Path = PARQUET_DIR,
    project_id: str | None = None,
    now: datetime | None = None,
) -> IngestResult:
    """Alle noch unbekannten Dokumente einlesen und die Parquet-Dateien fortschreiben."""
    ingested_at = now or datetime.now(UTC).replace(tzinfo=None)
    known_ids = set(read_table(parquet_dir, "documents")["document_id"])

    documents: list[Document] = []
    segments: list[Segment] = []
    chunks: list[Chunk] = []
    skipped = 0

    for path in discover(raw_dir, project_id):
        document = build_document(path, raw_dir=raw_dir, ingested_at=ingested_at)
        if document.document_id in known_ids:
            skipped += 1
            continue

        document_segments = extract(document, path.read_bytes())
        documents.append(document)
        segments.extend(document_segments)
        chunks.extend(chunk_segments(document, document_segments))
        known_ids.add(document.document_id)

    append_table(parquet_dir, "documents", documents)
    append_table(parquet_dir, "segments", segments)
    append_table(parquet_dir, "chunks", chunks)

    return IngestResult(
        documents=len(documents),
        skipped=skipped,
        segments=len(segments),
        chunks=len(chunks),
    )


def discover(raw_dir: Path, project_id: str | None) -> list[Path]:
    """Unterstützte Dateien eines oder aller Projekte, in stabiler Reihenfolge."""
    root = raw_dir / project_id if project_id else raw_dir
    if not root.is_dir():
        return []
    return sorted(
        p
        for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES
    )


def build_document(path: Path, *, raw_dir: Path, ingested_at: datetime) -> Document:
    relative = path.relative_to(raw_dir)
    return Document.from_file(
        path,
        project_id=relative.parts[0],
        raw_root=raw_dir,
        doc_type=doc_type_for(relative),
        media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        document_date=date_from_name(path.name),
        ingested_at=ingested_at,
    )


def doc_type_for(relative: Path) -> DocType:
    """Dokumentart aus dem Ordner unter der Projekt-ID."""
    folders = relative.parts[1:-1]
    for folder in folders:
        if found := DOC_TYPE_BY_FOLDER.get(folder.lower()):
            return found
    return DocType.UNBEKANNT


def date_from_name(file_name: str) -> date | None:
    """Datum aus dem Dateinamen lesen (``2026-09-15`` oder ``2026-09``).

    Bewusst einfach: Ein Monat ohne Tag wird auf den Monatsersten gesetzt. Das inhaltlich
    genauere Datum („Stand 15.09.2026“) steht im Dokument selbst und wäre eine eigene
    Auswertung – für die zeitliche Reihenfolge reicht der Dateiname.
    """
    match = DATE_PATTERN.search(file_name)
    if not match:
        return None
    return date(int(match["year"]), int(match["month"]), int(match["day"] or 1))


def read_table(parquet_dir: Path, name: str) -> pl.DataFrame:
    """Bestehende Tabelle lesen, oder eine leere mit festem Schema."""
    path = parquet_dir / f"{name}.parquet"
    if path.exists():
        return pl.read_parquet(path)
    return pl.DataFrame(schema=SCHEMAS[TABLES[name]])


def append_table(parquet_dir: Path, name: str, items: list) -> None:  # type: ignore[type-arg]
    """Neue Zeilen anhängen und die Datei neu schreiben.

    Vollständiges Neuschreiben statt Anhängen an die Datei: bei dieser Datenmenge einfach
    und nachvollziehbar. Wächst der Bestand, wird daraus ein partitionierter Datensatz
    (ein Verzeichnis je Projekt) oder eine Tabelle in PostgreSQL.
    """
    parquet_dir.mkdir(parents=True, exist_ok=True)
    frame = pl.concat([read_table(parquet_dir, name), to_frame(items, TABLES[name])])  # type: ignore[arg-type]
    frame.write_parquet(parquet_dir / f"{name}.parquet")
