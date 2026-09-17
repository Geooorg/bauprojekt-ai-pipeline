"""Datenmodelle (Pydantic) und zugehörige Polars-Schemas: Document, Segment, Chunk.

Drei Ebenen:

* ``Document`` – eine Version einer Datei. Die Identität umfasst Projekt, Pfad und
  Inhalts-Hash: Dieselbe Datei in zwei Projekten sind zwei Dokumente, sonst würde die
  zweite übersprungen und ihr Inhalt läge nur unter dem ersten Projekt.
* ``Segment``  – eine Einheit im Dokument: PDF-Seite, TOP eines Protokolls, Zeile im Terminplan.
  Ergebnis der Extraktion. Wird gespeichert, damit neu gechunkt werden kann, ohne erneut
  aus den Originalen zu lesen.
* ``Chunk``    – die Einheit, die eingebettet und durchsucht wird. Trägt ihre Herkunft
  redundant mit sich, damit ein Suchtreffer ohne Join zitierfähig ist und die
  Projekttrennung mit einer einzigen Bedingung auf ``project_id`` gelingt.

Die IDs von Segment und Chunk sind aus dem Inhalt abgeleitet und damit stabil: Ein
erneuter Durchlauf erzeugt dieselben IDs und kann bestehende Einträge überschreiben,
statt sie zu verdoppeln.
"""

import hashlib
import unicodedata
from collections.abc import Mapping
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Self

import polars as pl
from polars.datatypes import DataTypeClass
from pydantic import BaseModel, ConfigDict, Field

ID_LENGTH = 32
"""Hex-Zeichen abgeleiteter IDs. 32 Zeichen = 128 Bit, für Kollisionen praktisch ausreichend."""


class DocType(StrEnum):
    """Dokumentart. Wird vorerst aus dem Ordnernamen abgeleitet, später ggf. klassifiziert."""

    PROTOKOLL = "protokoll"
    STATUSBERICHT = "statusbericht"
    TERMINPLAN = "terminplan"
    GENEHMIGUNG = "genehmigung"
    UNBEKANNT = "unbekannt"


class SegmentKind(StrEnum):
    """Art der Einheit, in der ein Dokument extrahiert wird."""

    SEITE = "seite"
    ABSCHNITT = "abschnitt"
    TABELLENZEILE = "tabellenzeile"


def normalize_text(value: str) -> str:
    """Unicode auf NFC vereinheitlichen.

    macOS speichert Umlaute in Dateinamen zerlegt (NFD: ``o`` + Trema), Linux und Git
    üblicherweise zusammengesetzt (NFC). Ohne Normalisierung wäre
    ``behördenkorrespondenz.pdf`` je nach Herkunft ein anderer Pfad.
    """
    return unicodedata.normalize("NFC", value)


def hash_file(path: Path) -> str:
    """SHA-256 des Dateiinhalts als Hex. Identität einer Dokumentversion."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def derive_id(*parts: str | int) -> str:
    """Stabile ID aus ihren Bestandteilen ableiten (gleiche Bestandteile, gleiche ID)."""
    joined = "\x1f".join(str(part) for part in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:ID_LENGTH]


class Document(BaseModel):
    """Eine Version einer Originaldatei. Das Original selbst bleibt unverändert liegen."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    document_id: str = Field(
        description="Abgeleitet aus Projekt, Pfad und Inhalts-Hash. Gleiche Datei am gleichen Ort = gleiche ID."
    )
    content_hash: str = Field(description="SHA-256 des Dateiinhalts (Hex, 64 Zeichen)")
    project_id: str = Field(description="Projektzuordnung, z. B. 'BAU-42'")
    source_path: str = Field(description="Pfad relativ zu data/raw, NFC-normalisiert")
    file_name: str
    doc_type: DocType
    media_type: str = Field(description="z. B. application/pdf")
    file_size: int
    document_date: date | None = Field(
        default=None,
        description="Inhaltliches Datum (Protokolldatum, Berichtsstand). Unterscheidet aktuelle von überholten Aussagen.",
    )
    ingested_at: datetime = Field(
        description="Zeitpunkt der Verarbeitung, nicht des Dokuments"
    )

    @classmethod
    def from_file(
        cls,
        path: Path,
        *,
        project_id: str,
        raw_root: Path,
        doc_type: DocType,
        media_type: str,
        document_date: date | None,
        ingested_at: datetime,
    ) -> Self:
        content_hash = hash_file(path)
        source_path = normalize_text(path.relative_to(raw_root).as_posix())
        return cls(
            document_id=derive_id(project_id, source_path, content_hash),
            content_hash=content_hash,
            project_id=project_id,
            source_path=source_path,
            file_name=normalize_text(path.name),
            doc_type=doc_type,
            media_type=media_type,
            file_size=path.stat().st_size,
            document_date=document_date,
            ingested_at=ingested_at,
        )


class Segment(BaseModel):
    """Eine Einheit innerhalb eines Dokuments, so wie die Extraktion sie vorfindet."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    segment_id: str
    document_id: str
    project_id: str
    index: int = Field(description="Reihenfolge im Dokument, ab 0")
    kind: SegmentKind
    page_no: int | None = Field(
        default=None, description="Seitenzahl ab 1, None bei DOCX/XLSX"
    )
    locator: str = Field(
        description="Fundstelle für Menschen, z. B. 'S. 2', 'TOP 3', 'Zeile V02'"
    )
    heading: str | None = Field(
        default=None, description="Überschrift oder Thema, falls vorhanden"
    )
    text: str = Field(description="Extrahierter Text, unverändert übernommen")

    @classmethod
    def create(
        cls,
        *,
        document: Document,
        index: int,
        kind: SegmentKind,
        locator: str,
        text: str,
        page_no: int | None = None,
        heading: str | None = None,
    ) -> Self:
        return cls(
            segment_id=derive_id(document.document_id, index),
            document_id=document.document_id,
            project_id=document.project_id,
            index=index,
            kind=kind,
            page_no=page_no,
            locator=locator,
            heading=heading,
            text=text,
        )


class Chunk(BaseModel):
    """Die durchsuchbare Einheit. Trägt ihre Herkunft vollständig mit sich."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    chunk_id: str
    segment_id: str
    document_id: str
    project_id: str
    index: int = Field(description="Reihenfolge im Dokument, ab 0")
    text: str
    char_start: int = Field(
        description="Beginn im Segmenttext, für Textausschnitte und Hervorhebung"
    )
    char_end: int

    # Redundante Herkunft: macht einen Treffer allein zitierfähig und erlaubt das
    # Filtern nach Projekt, Dokumentart und Datum ohne Join.
    source_path: str
    file_name: str
    doc_type: DocType
    document_date: date | None = None
    page_no: int | None = None
    locator: str
    heading: str | None = None

    @classmethod
    def create(
        cls,
        *,
        document: Document,
        segment: Segment,
        index: int,
        text: str,
        char_start: int,
        char_end: int,
    ) -> Self:
        return cls(
            chunk_id=derive_id(segment.segment_id, index),
            segment_id=segment.segment_id,
            document_id=document.document_id,
            project_id=document.project_id,
            index=index,
            text=text,
            char_start=char_start,
            char_end=char_end,
            source_path=document.source_path,
            file_name=document.file_name,
            doc_type=document.doc_type,
            document_date=document.document_date,
            page_no=segment.page_no,
            locator=segment.locator,
            heading=segment.heading,
        )

    def citation(self) -> str:
        """Quellenangabe in einer Zeile, z. B. 'BAU-42 · statusbericht_2026-09.pdf · S. 2 · 15.09.2026'."""
        parts = [self.project_id, self.file_name, self.locator]
        if self.document_date is not None:
            parts.append(self.document_date.strftime("%d.%m.%Y"))
        return " · ".join(parts)


# --------------------------------------------------------------------------- Polars-Schemas
#
# Explizit festgelegt statt aus den Daten abgeleitet: Das Parquet-Schema bleibt damit über
# Läufe hinweg gleich, auch wenn eine Spalte in einem Durchlauf nur Null-Werte enthält.


def _schema(fields: Mapping[str, pl.DataType | DataTypeClass]) -> pl.Schema:
    """Nur zur Typisierung: Ohne diesen Umweg leitet mypy aus dem Literal ``dict[str, object]`` ab."""
    return pl.Schema(fields)


DOCUMENT_SCHEMA = _schema(
    {
        "document_id": pl.String,
        "content_hash": pl.String,
        "project_id": pl.String,
        "source_path": pl.String,
        "file_name": pl.String,
        "doc_type": pl.String,
        "media_type": pl.String,
        "file_size": pl.Int64,
        "document_date": pl.Date,
        "ingested_at": pl.Datetime("us"),
    }
)

SEGMENT_SCHEMA = _schema(
    {
        "segment_id": pl.String,
        "document_id": pl.String,
        "project_id": pl.String,
        "index": pl.Int32,
        "kind": pl.String,
        "page_no": pl.Int32,
        "locator": pl.String,
        "heading": pl.String,
        "text": pl.String,
    }
)

CHUNK_SCHEMA = _schema(
    {
        "chunk_id": pl.String,
        "segment_id": pl.String,
        "document_id": pl.String,
        "project_id": pl.String,
        "index": pl.Int32,
        "text": pl.String,
        "char_start": pl.Int32,
        "char_end": pl.Int32,
        "source_path": pl.String,
        "file_name": pl.String,
        "doc_type": pl.String,
        "document_date": pl.Date,
        "page_no": pl.Int32,
        "locator": pl.String,
        "heading": pl.String,
    }
)

SCHEMAS: dict[type[BaseModel], pl.Schema] = {
    Document: DOCUMENT_SCHEMA,
    Segment: SEGMENT_SCHEMA,
    Chunk: CHUNK_SCHEMA,
}


def to_frame[T: BaseModel](items: list[T], model: type[T]) -> pl.DataFrame:
    """Modelle in einen DataFrame mit festem Schema überführen (auch bei leerer Liste)."""
    schema = SCHEMAS[model]
    return pl.DataFrame([item.model_dump() for item in items], schema=schema)
