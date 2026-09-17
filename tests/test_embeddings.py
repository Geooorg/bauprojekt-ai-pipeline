"""Tests für bauprojekt.embeddings.

Ohne echtes Modell: Ein Doppel merkt sich die Eingaben. Geprüft wird, *was* eingebettet
wird – Präfixe, Kontext, Stapelgröße –, nicht die Qualität des Modells.
"""

import pytest
from conftest import make_document

from bauprojekt.config import EMBEDDING_DIM
from bauprojekt.embeddings import embed_chunks, embed_query, passage_text, query_text
from bauprojekt.models import Chunk, DocType, Segment, SegmentKind

DOKUMENT = make_document(
    file_name="statusbericht_2026-09.pdf",
    doc_type=DocType.STATUSBERICHT,
    media_type="application/pdf",
)

DIMENSION = EMBEDDING_DIM


class FakeEncoder:
    """Doppel für SentenceTransformer: merkt sich die Aufrufe."""

    def __init__(self, dimension: int = DIMENSION) -> None:
        self.dimension = dimension
        self.calls: list[list[str]] = []

    def encode(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [[float(len(text))] * self.dimension for text in texts]

    @property
    def eingaben(self) -> list[str]:
        return [text for call in self.calls for text in call]


def chunk(
    text: str, *, index: int = 0, heading: str | None = "2. Termine und Genehmigungen"
) -> Chunk:
    segment = Segment.create(
        document=DOKUMENT,
        index=index,
        kind=SegmentKind.SEITE,
        page_no=2,
        locator="S. 2",
        heading=heading,
        text=text,
    )
    return Chunk.create(
        document=DOKUMENT,
        segment=segment,
        index=index,
        text=text,
        char_start=0,
        char_end=len(text),
    )


class TestEingabetext:
    def test_passage_bekommt_praefix(self) -> None:
        """E5-Modelle erwarten 'passage: ' – ohne Präfix liegen Frage und Fundstelle weiter auseinander."""
        assert passage_text(chunk("Der Antrag ruht.")).startswith("passage: ")

    def test_query_bekommt_praefix(self) -> None:
        assert (
            query_text("Welche Genehmigungen sind offen?")
            == "query: Welche Genehmigungen sind offen?"
        )

    def test_ueberschrift_gibt_kontext(self) -> None:
        """Die Überschrift wandert in die Eingabe, nicht in den Chunk-Text."""
        eintrag = chunk("Der Antrag ruht.")
        assert "2. Termine und Genehmigungen" in passage_text(eintrag)
        assert eintrag.text == "Der Antrag ruht."

    def test_ohne_ueberschrift_nur_der_text(self) -> None:
        assert (
            passage_text(chunk("Der Antrag ruht.", heading=None))
            == "passage: Der Antrag ruht."
        )


class TestEinbetten:
    def test_liefert_paare_in_gleicher_reihenfolge(self) -> None:
        chunks = [chunk("erster", index=0), chunk("zweiter", index=1)]
        paare = embed_chunks(chunks, encoder=FakeEncoder())
        assert [eintrag.chunk_id for eintrag, _ in paare] == [
            c.chunk_id for c in chunks
        ]

    def test_bettet_den_praefixtext_ein(self) -> None:
        encoder = FakeEncoder()
        embed_chunks([chunk("Der Antrag ruht.")], encoder=encoder)
        assert encoder.eingaben == [
            "passage: 2. Termine und Genehmigungen\nDer Antrag ruht."
        ]

    def test_verarbeitet_in_stapeln(self) -> None:
        """Alles auf einmal einzubetten sprengt bei vielen Chunks den Speicher."""
        encoder = FakeEncoder()
        embed_chunks(
            [chunk(f"Text {i}", index=i) for i in range(5)],
            encoder=encoder,
            batch_size=2,
        )
        assert [len(call) for call in encoder.calls] == [2, 2, 1]

    def test_ohne_chunks_kein_modellaufruf(self) -> None:
        encoder = FakeEncoder()
        assert embed_chunks([], encoder=encoder) == []
        assert encoder.calls == []

    def test_frage_wird_eingebettet(self) -> None:
        encoder = FakeEncoder()
        vektor = embed_query("Welche Genehmigungen sind offen?", encoder=encoder)
        assert len(vektor) == DIMENSION
        assert encoder.eingaben == ["query: Welche Genehmigungen sind offen?"]


class TestFehler:
    def test_falsche_dimension_faellt_sofort_auf(self) -> None:
        """Ein Modell mit anderer Dimension muss hier auffallen, nicht erst beim Schreiben."""
        with pytest.raises(ValueError, match="Dimension"):
            embed_chunks([chunk("Text")], encoder=FakeEncoder(dimension=4))
