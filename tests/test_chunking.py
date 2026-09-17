"""Tests für bauprojekt.chunking."""

from itertools import pairwise

import pytest
from conftest import make_document

from bauprojekt.chunking import chunk_segments
from bauprojekt.models import Chunk, DocType, Document, Segment, SegmentKind

DOKUMENT = make_document(
    file_name="statusbericht_2026-09.pdf",
    doc_type=DocType.STATUSBERICHT,
    media_type="application/pdf",
)

SATZ = "Die Baugenehmigung für Haus B ist nicht erteilt, weil der Prüfbericht Brandschutz fehlt. "
LANGER_TEXT = "\n".join(SATZ * 4 for _ in range(6))  # rund 2100 Zeichen in 6 Absätzen


def segment(
    text: str,
    *,
    kind: SegmentKind = SegmentKind.SEITE,
    index: int = 0,
    document: Document = DOKUMENT,
    locator: str = "S. 2",
    page_no: int | None = 2,
    heading: str | None = "2. Termine und Genehmigungen",
) -> Segment:
    return Segment.create(
        document=document,
        index=index,
        kind=kind,
        page_no=page_no,
        locator=locator,
        heading=heading,
        text=text,
    )


class TestGroesse:
    def test_kurzes_segment_bleibt_ein_chunk(self) -> None:
        seg = segment("Gesamtstatus: ROT.")
        chunks = chunk_segments(DOKUMENT, [seg])
        assert len(chunks) == 1
        assert chunks[0].text == "Gesamtstatus: ROT."

    def test_langes_segment_wird_geteilt(self) -> None:
        chunks = chunk_segments(DOKUMENT, [segment(LANGER_TEXT)], max_chars=600)
        assert len(chunks) > 1
        assert all(len(chunk.text) <= 600 for chunk in chunks)

    def test_tabellenzeile_wird_nie_geteilt(self) -> None:
        """Eine Zeile ist eine Sinneinheit. Geteilt verlöre sie den Bezug zwischen den Spalten."""
        zeile = segment(
            "TOP: 3\nThema: Brandschutzprüfung\nSachstand: " + SATZ * 6,
            kind=SegmentKind.TABELLENZEILE,
            locator="TOP 3",
            page_no=None,
        )
        chunks = chunk_segments(DOKUMENT, [zeile], max_chars=200)
        assert len(chunks) == 1
        assert chunks[0].text == zeile.text


class TestGrenzen:
    def test_wird_an_satzgrenzen_getrennt(self) -> None:
        chunks = chunk_segments(DOKUMENT, [segment(LANGER_TEXT)], max_chars=600)
        assert all(chunk.text.endswith(".") for chunk in chunks)

    def test_jeder_chunk_beginnt_mit_einem_satz(self) -> None:
        """Auch der überlappende Teil startet an einer Satzgrenze, nicht mitten im Satz."""
        chunks = chunk_segments(DOKUMENT, [segment(LANGER_TEXT)], max_chars=600)
        assert all(chunk.text.startswith("Die ") for chunk in chunks)

    def test_ohne_trennstelle_wird_hart_geschnitten(self) -> None:
        chunks = chunk_segments(
            DOKUMENT, [segment("A" * 500)], max_chars=200, overlap=0
        )
        assert [len(chunk.text) for chunk in chunks] == [200, 200, 100]

    def test_chunks_ueberlappen(self) -> None:
        chunks = chunk_segments(
            DOKUMENT, [segment(LANGER_TEXT)], max_chars=600, overlap=150
        )
        assert chunks[1].char_start < chunks[0].char_end

    def test_ganzer_text_ist_abgedeckt(self) -> None:
        seg = segment(LANGER_TEXT)
        chunks = chunk_segments(DOKUMENT, [seg], max_chars=600)
        assert chunks[0].char_start == 0
        assert chunks[-1].char_end == len(
            seg.text.rstrip()
        )  # Leerraum am Ende entfällt
        for vorheriger, naechster in pairwise(chunks):
            assert naechster.char_start <= vorheriger.char_end


class TestHerkunft:
    @pytest.fixture
    def chunks(self) -> list[Chunk]:
        segmente = [
            segment("Gesamtstatus: ROT.", index=0, locator="S. 1", page_no=1),
            segment(LANGER_TEXT, index=1, locator="S. 2", page_no=2),
        ]
        return chunk_segments(DOKUMENT, segmente, max_chars=600)

    def test_offsets_zeigen_auf_den_segmenttext(self) -> None:
        seg = segment(LANGER_TEXT)
        for chunk in chunk_segments(DOKUMENT, [seg], max_chars=600):
            assert seg.text[chunk.char_start : chunk.char_end] == chunk.text

    def test_chunk_uebernimmt_fundstelle_des_segments(
        self, chunks: list[Chunk]
    ) -> None:
        assert chunks[0].locator == "S. 1"
        assert chunks[0].page_no == 1
        assert all(chunk.locator == "S. 2" for chunk in chunks[1:])

    def test_chunk_gehoert_zu_genau_einem_segment(self, chunks: list[Chunk]) -> None:
        """Ein Chunk reicht nie über eine Segmentgrenze – sonst wäre die Fundstelle mehrdeutig."""
        assert len({chunk.segment_id for chunk in chunks}) == 2
        assert chunks[0].text == "Gesamtstatus: ROT."

    def test_index_laeuft_ueber_das_ganze_dokument(self, chunks: list[Chunk]) -> None:
        assert [chunk.index for chunk in chunks] == list(range(len(chunks)))

    def test_ids_sind_eindeutig(self, chunks: list[Chunk]) -> None:
        assert len({chunk.chunk_id for chunk in chunks}) == len(chunks)

    def test_projekt_und_dokumentangaben_werden_durchgereicht(
        self, chunks: list[Chunk]
    ) -> None:
        assert {chunk.project_id for chunk in chunks} == {"BAU-42"}
        assert {chunk.document_id for chunk in chunks} == {DOKUMENT.document_id}
        assert (
            chunks[0].citation()
            == "BAU-42 · statusbericht_2026-09.pdf · S. 1 · 15.09.2026"
        )


def test_ohne_segmente_keine_chunks() -> None:
    assert chunk_segments(DOKUMENT, []) == []
