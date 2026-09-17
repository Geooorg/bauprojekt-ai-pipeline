"""Tests für bauprojekt.models."""

from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest
from pydantic import BaseModel

from bauprojekt.models import (
    SCHEMAS,
    Chunk,
    DocType,
    Document,
    Segment,
    SegmentKind,
    derive_id,
    hash_file,
    normalize_text,
    to_frame,
)

INGESTED_AT = datetime(2026, 9, 17, 8, 0, tzinfo=UTC).replace(tzinfo=None)


@pytest.fixture
def document(tmp_path: Path) -> Document:
    path = tmp_path / "BAU-42" / "statusberichte" / "statusbericht_2026-09.pdf"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"%PDF-1.7 Testinhalt")
    return Document.from_file(
        path,
        project_id="BAU-42",
        raw_root=tmp_path,
        doc_type=DocType.STATUSBERICHT,
        media_type="application/pdf",
        document_date=date(2026, 9, 15),
        ingested_at=INGESTED_AT,
    )


@pytest.fixture
def segment(document: Document) -> Segment:
    return Segment.create(
        document=document,
        index=1,
        kind=SegmentKind.SEITE,
        page_no=2,
        locator="S. 2",
        heading="2. Termine und Genehmigungen",
        text="Baugenehmigung Haus B: Antrag ruht.",
    )


class TestModelle:
    def test_dokument_id_ist_der_inhalts_hash(
        self, document: Document, tmp_path: Path
    ) -> None:
        assert document.document_id == hash_file(tmp_path / document.source_path)

    def test_gleicher_inhalt_ergibt_gleiche_id(
        self, document: Document, tmp_path: Path
    ) -> None:
        kopie = tmp_path / "BAU-42" / "protokolle" / "andere_datei.pdf"
        kopie.parent.mkdir(parents=True)
        kopie.write_bytes(b"%PDF-1.7 Testinhalt")
        assert hash_file(kopie) == document.document_id

    def test_geaenderter_inhalt_ergibt_neue_id(
        self, document: Document, tmp_path: Path
    ) -> None:
        pfad = tmp_path / document.source_path
        pfad.write_bytes(b"%PDF-1.7 Testinhalt, korrigiert")
        assert hash_file(pfad) != document.document_id

    def test_pfad_ist_relativ_und_nfc_normalisiert(self, tmp_path: Path) -> None:
        zerlegt = normalize_text("behördenkorrespondenz.pdf").replace("ö", "ö")
        pfad = tmp_path / "BAU-42" / "genehmigungen" / zerlegt
        pfad.parent.mkdir(parents=True)
        pfad.write_bytes(b"%PDF-1.7")
        dokument = Document.from_file(
            pfad,
            project_id="BAU-42",
            raw_root=tmp_path,
            doc_type=DocType.GENEHMIGUNG,
            media_type="application/pdf",
            document_date=None,
            ingested_at=INGESTED_AT,
        )
        assert dokument.source_path == "BAU-42/genehmigungen/behördenkorrespondenz.pdf"
        assert dokument.file_name == "behördenkorrespondenz.pdf"

    def test_abgeleitete_ids_sind_stabil_und_verschieden(
        self, document: Document, segment: Segment
    ) -> None:
        assert segment.segment_id == derive_id(document.document_id, 1)
        assert derive_id(document.document_id, 1) != derive_id(document.document_id, 2)

    def test_chunk_traegt_herkunft_ohne_join(
        self, document: Document, segment: Segment
    ) -> None:
        chunk = Chunk.create(
            document=document,
            segment=segment,
            index=0,
            text="Baugenehmigung Haus B: Antrag ruht.",
            char_start=0,
            char_end=35,
        )
        assert chunk.project_id == "BAU-42"
        assert chunk.page_no == 2
        assert chunk.document_date == date(2026, 9, 15)
        assert (
            chunk.citation() == "BAU-42 · statusbericht_2026-09.pdf · S. 2 · 15.09.2026"
        )

    def test_modelle_sind_unveraenderlich(self, document: Document) -> None:
        with pytest.raises(ValueError, match="frozen"):
            document.project_id = "BAU-43"  # type: ignore[misc]


class TestSchemas:
    @pytest.mark.parametrize("model", list(SCHEMAS))
    def test_schema_deckt_genau_die_modellfelder_ab(
        self, model: type[BaseModel]
    ) -> None:
        assert list(SCHEMAS[model].keys()) == list(model.model_fields)

    def test_leere_liste_ergibt_frame_mit_schema(self) -> None:
        frame = to_frame([], Document)
        assert frame.height == 0
        assert frame.schema == SCHEMAS[Document]

    def test_frame_haelt_schema_ein(self, document: Document, segment: Segment) -> None:
        assert to_frame([document], Document).schema == SCHEMAS[Document]
        assert to_frame([segment], Segment).schema == SCHEMAS[Segment]

    def test_parquet_rundreise_erhaelt_werte(
        self, document: Document, tmp_path: Path
    ) -> None:
        pfad = tmp_path / "documents.parquet"
        to_frame([document], Document).write_parquet(pfad)
        gelesen = pl.read_parquet(pfad)
        assert gelesen.schema == SCHEMAS[Document]
        assert gelesen.row(0, named=True)["document_date"] == date(2026, 9, 15)
        assert gelesen.row(0, named=True)["doc_type"] == "statusbericht"
