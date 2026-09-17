"""Tests für bauprojekt.db.

Brauchen eine laufende Datenbank:
    podman compose -f infra/docker-compose.yml up -d postgres

Ohne Datenbank werden sie übersprungen, damit die übrigen Tests überall laufen.
"""

from datetime import date

import psycopg
import pytest
from conftest import make_document

from bauprojekt.config import EMBEDDING_DIM
from bauprojekt.db import fetch_known_chunk_ids, init_schema, upsert_chunks
from bauprojekt.models import Chunk, DocType, Segment, SegmentKind

pytestmark = pytest.mark.db

DOKUMENT = make_document(
    file_name="statusbericht_2026-09.pdf",
    doc_type=DocType.STATUSBERICHT,
    media_type="application/pdf",
)
DOKUMENT_43 = make_document(
    file_name="statusbericht_2026-09.pdf",
    doc_type=DocType.STATUSBERICHT,
    media_type="application/pdf",
    project_id="BAU-43",
)


def chunk(
    text: str, *, index: int = 0, document: object = DOKUMENT, locator: str = "S. 1"
) -> Chunk:
    dokument = document  # type: ignore[assignment]
    segment = Segment.create(
        document=dokument,  # type: ignore[arg-type]
        index=index,
        kind=SegmentKind.SEITE,
        page_no=1,
        locator=locator,
        heading="2. Termine und Genehmigungen",
        text=text,
    )
    return Chunk.create(
        document=dokument,  # type: ignore[arg-type]
        segment=segment,
        index=index,
        text=text,
        char_start=0,
        char_end=len(text),
    )


def vektor(wert: float) -> list[float]:
    return [wert] * EMBEDDING_DIM


class TestSchema:
    def test_tabelle_und_spalten_existieren(self, db: psycopg.Connection) -> None:
        spalten = {
            row[0]
            for row in db.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'chunks'"
            ).fetchall()
        }
        assert {"chunk_id", "project_id", "text", "embedding", "text_search"} <= spalten

    def test_embedding_hat_die_konfigurierte_dimension(
        self, db: psycopg.Connection
    ) -> None:
        with pytest.raises(psycopg.errors.DataException):
            db.execute(
                "INSERT INTO chunks (chunk_id, segment_id, document_id, project_id, index, text,"
                " char_start, char_end, source_path, file_name, doc_type, locator, embedding)"
                " VALUES ('x','y','z','BAU-42',0,'t',0,1,'p','f','protokoll','S. 1', %s)",
                ([0.1, 0.2],),
            )

    def test_schema_ist_wiederholbar(self, db: psycopg.Connection) -> None:
        init_schema(db)  # darf ohne Fehler erneut laufen
        init_schema(db)


class TestSchreiben:
    def test_chunks_werden_gespeichert(self, db: psycopg.Connection) -> None:
        upsert_chunks(
            db, [(chunk("Baugenehmigung Haus B ist nicht erteilt."), vektor(0.1))]
        )
        assert db.execute("SELECT count(*) FROM chunks").fetchone() == (1,)

    def test_zweimal_schreiben_verdoppelt_nicht(self, db: psycopg.Connection) -> None:
        """Stabile chunk_id + ON CONFLICT: ein erneuter Lauf aktualisiert statt zu verdoppeln."""
        eintrag = chunk("Der Antrag ruht.")
        upsert_chunks(db, [(eintrag, vektor(0.1))])
        upsert_chunks(db, [(eintrag, vektor(0.9))])

        zeile = db.execute("SELECT count(*) OVER (), embedding FROM chunks").fetchone()
        assert zeile is not None
        anzahl, embedding = zeile
        assert anzahl == 1
        assert embedding.to_list()[0] == pytest.approx(0.9)

    def test_herkunft_wird_mitgeschrieben(self, db: psycopg.Connection) -> None:
        upsert_chunks(db, [(chunk("Frist bis 30.09.2026."), vektor(0.1))])
        row = db.execute(
            "SELECT project_id, file_name, page_no, locator, document_date, heading FROM chunks"
        ).fetchone()
        assert row == (
            "BAU-42",
            "statusbericht_2026-09.pdf",
            1,
            "S. 1",
            date(2026, 9, 15),
            "2. Termine und Genehmigungen",
        )

    def test_bekannte_chunks_abfragbar(self, db: psycopg.Connection) -> None:
        eintrag = chunk("Nachtrag N-07 offen.")
        upsert_chunks(db, [(eintrag, vektor(0.1))])
        assert fetch_known_chunk_ids(db, project_id="BAU-42") == {eintrag.chunk_id}
        assert fetch_known_chunk_ids(db, project_id="BAU-43") == set()


class TestVolltext:
    def test_deutsche_suche_findet_gebeugte_form(self, db: psycopg.Connection) -> None:
        """Die Spalte text_search nutzt die deutsche Konfiguration – 'Fristen' findet 'Frist'."""
        upsert_chunks(
            db, [(chunk("Die Bauaufsicht hat eine Frist gesetzt."), vektor(0.1))]
        )
        treffer = db.execute(
            "SELECT count(*) FROM chunks WHERE text_search @@ plainto_tsquery('german', %s)",
            ("Fristen",),
        ).fetchone()
        assert treffer == (1,)

    def test_ueberschrift_ist_durchsuchbar(self, db: psycopg.Connection) -> None:
        upsert_chunks(db, [(chunk("Kein Verantwortlicher benannt."), vektor(0.1))])
        treffer = db.execute(
            "SELECT count(*) FROM chunks WHERE text_search @@ plainto_tsquery('german', %s)",
            ("Genehmigungen",),
        ).fetchone()
        assert treffer == (1,)


class TestProjekttrennung:
    def test_filter_auf_projekt_reicht(self, db: psycopg.Connection) -> None:
        upsert_chunks(
            db,
            [
                (chunk("Baugenehmigung Haus B ist nicht erteilt."), vektor(0.1)),
                (
                    chunk("Baugenehmigung vollständig erteilt.", document=DOKUMENT_43),
                    vektor(0.1),
                ),
            ],
        )
        treffer = db.execute(
            "SELECT text FROM chunks WHERE project_id = %s AND text_search @@ plainto_tsquery('german', %s)",
            ("BAU-42", "Baugenehmigung"),
        ).fetchall()
        assert treffer == [("Baugenehmigung Haus B ist nicht erteilt.",)]
