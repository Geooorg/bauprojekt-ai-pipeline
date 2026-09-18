"""Tests für bauprojekt.pipeline (Durchlauf von Anfang bis Ende, inkrementelle Verarbeitung)."""

from pathlib import Path

import polars as pl
import psycopg
import pytest
from conftest import FakeEncoder

from bauprojekt.models import SCHEMAS, Chunk, Document, Segment
from bauprojekt.pipeline import index_chunks, ingest


@pytest.fixture
def raw_dir(
    tmp_path: Path, pdf_bytes: bytes, docx_bytes: bytes, xlsx_bytes: bytes
) -> Path:
    """Kleiner Rohdatenbestand: zwei Projekte, drei Dokumentarten."""
    raw = tmp_path / "raw"
    dateien = {
        "BAU-42/statusberichte/statusbericht_2026-09.pdf": pdf_bytes,
        "BAU-42/protokolle/2026-09-15_baubesprechung.docx": docx_bytes,
        "BAU-42/terminplan/bauzeitenplan.xlsx": xlsx_bytes,
        "BAU-43/statusberichte/statusbericht_2026-09.pdf": pdf_bytes,
    }
    for pfad, inhalt in dateien.items():
        ziel = raw / pfad
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_bytes(inhalt)
    return raw


@pytest.fixture
def parquet_dir(tmp_path: Path) -> Path:
    return tmp_path / "parquet"


def lies(parquet_dir: Path, name: str) -> pl.DataFrame:
    return pl.read_parquet(parquet_dir / f"{name}.parquet")


class TestErsterDurchlauf:
    def test_schreibt_drei_dateien(self, raw_dir: Path, parquet_dir: Path) -> None:
        ingest(raw_dir=raw_dir, parquet_dir=parquet_dir)
        assert sorted(p.name for p in parquet_dir.glob("*.parquet")) == [
            "chunks.parquet",
            "documents.parquet",
            "segments.parquet",
        ]

    def test_meldet_was_verarbeitet_wurde(
        self, raw_dir: Path, parquet_dir: Path
    ) -> None:
        ergebnis = ingest(raw_dir=raw_dir, parquet_dir=parquet_dir)
        assert ergebnis.documents == 4
        assert ergebnis.skipped == 0
        assert ergebnis.chunks == lies(parquet_dir, "chunks").height

    def test_schemas_werden_eingehalten(self, raw_dir: Path, parquet_dir: Path) -> None:
        ingest(raw_dir=raw_dir, parquet_dir=parquet_dir)
        for name, modell in (
            ("documents", Document),
            ("segments", Segment),
            ("chunks", Chunk),
        ):
            assert lies(parquet_dir, name).schema == SCHEMAS[modell]

    def test_dokumentart_kommt_aus_dem_ordner(
        self, raw_dir: Path, parquet_dir: Path
    ) -> None:
        ingest(raw_dir=raw_dir, parquet_dir=parquet_dir)
        documents = lies(parquet_dir, "documents")
        arten = dict(zip(documents["file_name"], documents["doc_type"], strict=True))
        assert arten["2026-09-15_baubesprechung.docx"] == "protokoll"
        assert arten["bauzeitenplan.xlsx"] == "terminplan"

    def test_datum_kommt_aus_dem_dateinamen(
        self, raw_dir: Path, parquet_dir: Path
    ) -> None:
        ingest(raw_dir=raw_dir, parquet_dir=parquet_dir)
        documents = lies(parquet_dir, "documents")
        daten = dict(
            zip(documents["file_name"], documents["document_date"], strict=True)
        )
        assert str(daten["2026-09-15_baubesprechung.docx"]) == "2026-09-15"
        assert str(daten["statusbericht_2026-09.pdf"]) == "2026-09-01"

    def test_originale_bleiben_unveraendert(
        self, raw_dir: Path, parquet_dir: Path
    ) -> None:
        vorher = {p: p.read_bytes() for p in raw_dir.rglob("*") if p.is_file()}
        ingest(raw_dir=raw_dir, parquet_dir=parquet_dir)
        assert {p: p.read_bytes() for p in raw_dir.rglob("*") if p.is_file()} == vorher


class TestProjekttrennung:
    def test_jedes_dokument_traegt_sein_projekt(
        self, raw_dir: Path, parquet_dir: Path
    ) -> None:
        ingest(raw_dir=raw_dir, parquet_dir=parquet_dir)
        chunks = lies(parquet_dir, "chunks")
        aus_43 = chunks.filter(pl.col("project_id") == "BAU-43")
        assert aus_43.height > 0
        assert set(aus_43["source_path"].str.slice(0, 7)) == {"BAU-43/"}

    def test_einzelnes_projekt_verarbeitbar(
        self, raw_dir: Path, parquet_dir: Path
    ) -> None:
        ingest(raw_dir=raw_dir, parquet_dir=parquet_dir, project_id="BAU-42")
        assert set(lies(parquet_dir, "documents")["project_id"]) == {"BAU-42"}


class TestInkrementell:
    def test_zweiter_durchlauf_verarbeitet_nichts_neu(
        self, raw_dir: Path, parquet_dir: Path
    ) -> None:
        erster = ingest(raw_dir=raw_dir, parquet_dir=parquet_dir)
        vorher = lies(parquet_dir, "chunks")

        zweiter = ingest(raw_dir=raw_dir, parquet_dir=parquet_dir)

        assert zweiter.documents == 0
        assert zweiter.skipped == erster.documents
        assert lies(parquet_dir, "chunks").equals(vorher)

    def test_geaendertes_dokument_wird_neue_version(
        self, raw_dir: Path, parquet_dir: Path, docx_bytes: bytes
    ) -> None:
        ingest(raw_dir=raw_dir, parquet_dir=parquet_dir)
        pfad = raw_dir / "BAU-42/statusberichte/statusbericht_2026-09.pdf"
        pfad.write_bytes(docx_bytes)  # anderer Inhalt unter gleichem Pfad

        ergebnis = ingest(raw_dir=raw_dir, parquet_dir=parquet_dir)

        assert ergebnis.documents == 1
        versionen = lies(parquet_dir, "documents").filter(
            pl.col("source_path") == "BAU-42/statusberichte/statusbericht_2026-09.pdf"
        )
        assert versionen.height == 2
        assert versionen["document_id"].n_unique() == 2

    def test_neues_dokument_kommt_hinzu(
        self, raw_dir: Path, parquet_dir: Path, docx_bytes: bytes
    ) -> None:
        ingest(raw_dir=raw_dir, parquet_dir=parquet_dir)
        (raw_dir / "BAU-42/protokolle/2026-09-22_baubesprechung.docx").write_bytes(
            docx_bytes
        )

        ergebnis = ingest(raw_dir=raw_dir, parquet_dir=parquet_dir)

        assert ergebnis.documents == 1
        assert lies(parquet_dir, "documents").height == 5


class TestRobustheit:
    def test_unbekannte_dateiart_wird_uebersprungen(
        self, raw_dir: Path, parquet_dir: Path
    ) -> None:
        (raw_dir / "BAU-42/protokolle/notiz.txt").write_text("nur eine Notiz")
        ergebnis = ingest(raw_dir=raw_dir, parquet_dir=parquet_dir)
        assert ergebnis.documents == 4
        assert "notiz.txt" not in set(lies(parquet_dir, "documents")["file_name"])

    def test_unbekannter_ordner_ergibt_unbekannte_dokumentart(
        self, raw_dir: Path, parquet_dir: Path, pdf_bytes: bytes
    ) -> None:
        ziel = raw_dir / "BAU-42/sonstiges/irgendwas.pdf"
        ziel.parent.mkdir()
        ziel.write_bytes(pdf_bytes)
        ingest(raw_dir=raw_dir, parquet_dir=parquet_dir)
        documents = lies(parquet_dir, "documents")
        arten = dict(zip(documents["file_name"], documents["doc_type"], strict=True))
        assert arten["irgendwas.pdf"] == "unbekannt"

    def test_leeres_verzeichnis_ist_kein_fehler(
        self, tmp_path: Path, parquet_dir: Path
    ) -> None:
        leer = tmp_path / "leer"
        leer.mkdir()
        ergebnis = ingest(raw_dir=leer, parquet_dir=parquet_dir)
        assert ergebnis.documents == 0
        assert lies(parquet_dir, "documents").height == 0


@pytest.mark.db
class TestIndexieren:
    """Parquet → Embeddings → PostgreSQL."""

    def test_alle_chunks_landen_in_der_datenbank(
        self, raw_dir: Path, parquet_dir: Path, db: psycopg.Connection
    ) -> None:
        ingest(raw_dir=raw_dir, parquet_dir=parquet_dir)
        ergebnis = index_chunks(
            connection=db, encoder=FakeEncoder(), parquet_dir=parquet_dir
        )

        assert ergebnis.embedded == lies(parquet_dir, "chunks").height
        assert db.execute("SELECT count(*) FROM chunks").fetchone() == (
            ergebnis.embedded,
        )

    def test_zweiter_lauf_bettet_nichts_neu_ein(
        self, raw_dir: Path, parquet_dir: Path, db: psycopg.Connection
    ) -> None:
        """Einbetten kostet Rechenzeit – bekannte Chunks werden übersprungen."""
        ingest(raw_dir=raw_dir, parquet_dir=parquet_dir)
        index_chunks(connection=db, encoder=FakeEncoder(), parquet_dir=parquet_dir)

        encoder = FakeEncoder()
        ergebnis = index_chunks(connection=db, encoder=encoder, parquet_dir=parquet_dir)

        assert ergebnis.embedded == 0
        assert ergebnis.skipped == lies(parquet_dir, "chunks").height
        assert encoder.calls == []

    def test_nur_ein_projekt(
        self, raw_dir: Path, parquet_dir: Path, db: psycopg.Connection
    ) -> None:
        ingest(raw_dir=raw_dir, parquet_dir=parquet_dir)
        index_chunks(
            connection=db,
            encoder=FakeEncoder(),
            parquet_dir=parquet_dir,
            project_id="BAU-43",
        )
        projekte = db.execute("SELECT DISTINCT project_id FROM chunks").fetchall()
        assert projekte == [("BAU-43",)]

    def test_ohne_parquet_kein_fehler(
        self, parquet_dir: Path, db: psycopg.Connection
    ) -> None:
        ergebnis = index_chunks(
            connection=db, encoder=FakeEncoder(), parquet_dir=parquet_dir
        )
        assert ergebnis.embedded == 0


class TestProjektIdAmEingang:
    """G1 und G2 aus docs/spezifikation.md."""

    def test_lose_datei_wird_abgewiesen_und_gemeldet(
        self, raw_dir: Path, parquet_dir: Path, pdf_bytes: bytes
    ) -> None:
        """G1: Eine Datei ohne Projektordner wird kein Scheinprojekt."""
        (raw_dir / "lose_datei.pdf").write_bytes(pdf_bytes)

        ergebnis = ingest(raw_dir=raw_dir, parquet_dir=parquet_dir)

        assert ergebnis.rejected == ["lose_datei.pdf"]
        assert ergebnis.documents == 4  # die übrigen werden trotzdem eingelesen
        assert set(lies(parquet_dir, "documents")["project_id"]) == {"BAU-42", "BAU-43"}

    def test_ordner_mit_ungueltigem_namen_wird_abgewiesen(
        self, raw_dir: Path, parquet_dir: Path, pdf_bytes: bytes
    ) -> None:
        ziel = raw_dir / "entwurf" / "statusberichte" / "bericht.pdf"
        ziel.parent.mkdir(parents=True)
        ziel.write_bytes(pdf_bytes)

        ergebnis = ingest(raw_dir=raw_dir, parquet_dir=parquet_dir)

        assert ergebnis.rejected == ["entwurf/statusberichte/bericht.pdf"]

    @pytest.mark.parametrize("projekt", ["..", "BAU-42/..", "../raw"])
    def test_pfadbestandteile_als_projekt_id_werden_abgelehnt(
        self, raw_dir: Path, parquet_dir: Path, projekt: str
    ) -> None:
        """G2: Der Filter lässt sich nicht über '..' umgehen."""
        with pytest.raises(ValueError, match="Projekt-ID"):
            ingest(raw_dir=raw_dir, parquet_dir=parquet_dir, project_id=projekt)
        assert not (parquet_dir / "documents.parquet").exists()

    @pytest.mark.db
    def test_index_chunks_prueft_die_projekt_id(
        self, parquet_dir: Path, db: psycopg.Connection
    ) -> None:
        with pytest.raises(ValueError, match="Projekt-ID"):
            index_chunks(
                connection=db,
                encoder=FakeEncoder(),
                parquet_dir=parquet_dir,
                project_id="..",
            )
