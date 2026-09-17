"""Tests für bauprojekt.extraction."""

import pytest
from conftest import make_document

from bauprojekt.extraction import extract
from bauprojekt.models import DocType, Segment, SegmentKind

PDF_DOKUMENT = make_document(
    file_name="statusbericht_2026-09.pdf",
    doc_type=DocType.STATUSBERICHT,
    media_type="application/pdf",
)
DOCX_DOKUMENT = make_document(
    file_name="2026-09-15_baubesprechung.docx",
    doc_type=DocType.PROTOKOLL,
    media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
)
XLSX_DOKUMENT = make_document(
    file_name="bauzeitenplan.xlsx",
    doc_type=DocType.TERMINPLAN,
    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)


class TestPdf:
    def test_eine_seite_ergibt_ein_segment(self, pdf_bytes: bytes) -> None:
        segmente = extract(PDF_DOKUMENT, pdf_bytes)
        assert [segment.page_no for segment in segmente] == [1, 2]
        assert [segment.kind for segment in segmente] == [SegmentKind.SEITE] * 2

    def test_locator_nennt_die_seite(self, pdf_bytes: bytes) -> None:
        assert [segment.locator for segment in extract(PDF_DOKUMENT, pdf_bytes)] == [
            "S. 1",
            "S. 2",
        ]

    def test_text_wird_uebernommen(self, pdf_bytes: bytes) -> None:
        segmente = extract(PDF_DOKUMENT, pdf_bytes)
        assert "Gesamtstatus: ROT." in segmente[0].text
        assert "Antrag ruht" in segmente[1].text

    def test_ueberschrift_wird_erkannt(self, pdf_bytes: bytes) -> None:
        assert extract(PDF_DOKUMENT, pdf_bytes)[1].heading == "2. Termine"


class TestDocx:
    def test_tabellenzeile_bleibt_zusammen(self, docx_bytes: bytes) -> None:
        """Thema, Sachstand und Verantwortlicher gehören in ein Segment.

        Zerfielen sie in einzelne Zellen, ginge der Bezug verloren – und mit ihm die
        Antwort auf Fragen wie „Wer ist verantwortlich?“.
        """
        zeilen = [
            s
            for s in extract(DOCX_DOKUMENT, docx_bytes)
            if s.kind is SegmentKind.TABELLENZEILE
        ]
        assert len(zeilen) == 2
        text = zeilen[1].text
        assert "Thema: Brandschutzprüfung" in text
        assert "Sachstand: Kein Verantwortlicher benannt." in text
        assert "Verantwortlich: ungeklärt" in text

    def test_kopfzeile_ist_kein_eigenes_segment(self, docx_bytes: bytes) -> None:
        assert all(
            "Thema: Thema" not in s.text for s in extract(DOCX_DOKUMENT, docx_bytes)
        )

    def test_locator_nennt_den_top(self, docx_bytes: bytes) -> None:
        zeilen = [
            s
            for s in extract(DOCX_DOKUMENT, docx_bytes)
            if s.kind is SegmentKind.TABELLENZEILE
        ]
        assert [zeile.locator for zeile in zeilen] == ["TOP 1", "TOP 2"]

    def test_absaetze_werden_nach_ueberschrift_gruppiert(
        self, docx_bytes: bytes
    ) -> None:
        abschnitte = [
            s
            for s in extract(DOCX_DOKUMENT, docx_bytes)
            if s.kind is SegmentKind.ABSCHNITT
        ]
        assert abschnitte[0].heading == "Protokoll Baubesprechung Nr. 25"
        assert "Projekt: BAU-42" in abschnitte[0].text

    def test_absatz_nach_tabelle_erbt_nicht_deren_ueberschrift(
        self, docx_bytes: bytes
    ) -> None:
        """Sonst stünde über dem Schlussabsatz „Tagesordnungspunkte“ – eine falsche Fundstelle."""
        letzter = extract(DOCX_DOKUMENT, docx_bytes)[-1]
        assert "Nächste Baubesprechung" in letzter.text
        assert letzter.heading is None

    def test_ohne_seitenzahl(self, docx_bytes: bytes) -> None:
        assert all(
            segment.page_no is None for segment in extract(DOCX_DOKUMENT, docx_bytes)
        )


class TestXlsx:
    def test_zeile_wird_zu_segment_mit_spaltennamen(self, xlsx_bytes: bytes) -> None:
        zeilen = [
            s
            for s in extract(XLSX_DOKUMENT, xlsx_bytes)
            if s.kind is SegmentKind.TABELLENZEILE
        ]
        assert len(zeilen) == 2
        assert "Vorgang: Rohbau Haus A" in zeilen[0].text
        assert "Verzug (AT): 10" in zeilen[0].text

    def test_leere_zellen_entfallen(self, xlsx_bytes: bytes) -> None:
        zeilen = [
            s
            for s in extract(XLSX_DOKUMENT, xlsx_bytes)
            if s.kind is SegmentKind.TABELLENZEILE
        ]
        assert "Verzug (AT)" not in zeilen[1].text

    def test_locator_nennt_die_vorgangs_id(self, xlsx_bytes: bytes) -> None:
        zeilen = [
            s
            for s in extract(XLSX_DOKUMENT, xlsx_bytes)
            if s.kind is SegmentKind.TABELLENZEILE
        ]
        assert [zeile.locator for zeile in zeilen] == [
            "Bauzeitenplan, Zeile V02",
            "Bauzeitenplan, Zeile V07",
        ]

    def test_titelzeile_ueber_der_kopfzeile_geht_nicht_verloren(
        self, xlsx_bytes: bytes
    ) -> None:
        segmente = extract(XLSX_DOKUMENT, xlsx_bytes)
        assert segmente[0].kind is SegmentKind.ABSCHNITT
        assert "Bauzeitenplan BAU-42" in segmente[0].text


class TestGemeinsameZusicherungen:
    @pytest.fixture(params=["pdf", "docx", "xlsx"])
    def segmente(self, request: pytest.FixtureRequest) -> list[Segment]:
        dokument, daten = {
            "pdf": (PDF_DOKUMENT, "pdf_bytes"),
            "docx": (DOCX_DOKUMENT, "docx_bytes"),
            "xlsx": (XLSX_DOKUMENT, "xlsx_bytes"),
        }[request.param]
        return extract(dokument, request.getfixturevalue(daten))

    def test_index_laeuft_luechenlos_ab_null(self, segmente: list[Segment]) -> None:
        assert [segment.index for segment in segmente] == list(range(len(segmente)))

    def test_ids_sind_eindeutig(self, segmente: list[Segment]) -> None:
        assert len({segment.segment_id for segment in segmente}) == len(segmente)

    def test_projektzuordnung_wird_durchgereicht(self, segmente: list[Segment]) -> None:
        assert {segment.project_id for segment in segmente} == {"BAU-42"}

    def test_kein_leeres_segment(self, segmente: list[Segment]) -> None:
        assert all(segment.text.strip() for segment in segmente)


def test_unbekannte_dateiendung_wird_abgelehnt() -> None:
    dokument = make_document(
        file_name="plan.dwg", doc_type=DocType.UNBEKANNT, media_type="application/acad"
    )
    with pytest.raises(ValueError, match="dwg"):
        extract(dokument, b"egal")
