"""Hybrid-Suche: Vektor- und Volltextsuche, zusammengeführt per Reciprocal Rank Fusion.

Warum zwei Verfahren?

* Die **Vektorsuche** versteht Bedeutung: „Welche Genehmigungen sind offen?“ findet auch
  „Der Antrag ruht“, obwohl kein Wort übereinstimmt. Sie ist aber unscharf bei genauen
  Begriffen – Aktenzeichen, Nachtragsnummern, Namen.
* Die **Volltextsuche** findet genau diese Begriffe zuverlässig („N-07“, „BA-2026-0587“),
  versteht aber keine Umschreibungen. Und sie zerlegt keine zusammengesetzten Wörter:
  „Genehmigungen“ wird zu ``genehm``, „Baugenehmigung“ zu ``baugenehm`` – kein Treffer.
  Im Deutschen ist das keine Randerscheinung, sondern der Normalfall.

Beide liefern eine Rangliste. Die Rohwerte sind nicht vergleichbar (Cosinus-Ähnlichkeit
gegen Textrang), die **Ränge** schon. Reciprocal Rank Fusion vergibt je Liste
``1 / (k + Rang)`` Punkte und addiert – wer in beiden Listen weit oben steht, gewinnt.

``project_id`` ist in jeder Funktion ein Pflichtargument ohne Vorgabe. Eine Suche über alle
Projekte ist damit gar nicht formulierbar – die Projekttrennung hängt nicht davon ab, dass
jemand daran denkt.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import psycopg

from bauprojekt.config import TEXT_SEARCH_CONFIG
from bauprojekt.db import COLUMNS
from bauprojekt.embeddings import Encoder, embed_query
from bauprojekt.models import Chunk

RRF_K = 60
"""Dämpfung der Rangfusion. 60 ist der Wert aus der Originalarbeit und gängiger Standard:
Er verhindert, dass ein einzelner Spitzenplatz in nur einer Liste alles andere überstimmt."""

CANDIDATES_PER_METHOD = 30
"""So viele Kandidaten holt jedes Verfahren, bevor fusioniert wird."""

CHUNK_COLUMNS = [column for column in COLUMNS if column != "embedding"]
SELECT_CHUNK = ", ".join(CHUNK_COLUMNS)


@dataclass(frozen=True)
class SearchHit:
    """Ein Treffer mit Herkunft und Nachweis, wie er zustande kam."""

    chunk: Chunk
    score: float
    vector_rank: int | None
    text_rank: int | None


def search(
    connection: psycopg.Connection,
    *,
    project_id: str,
    question: str,
    encoder: Encoder,
    limit: int = 10,
    candidates: int = CANDIDATES_PER_METHOD,
) -> list[SearchHit]:
    """Hybrid-Suche innerhalb eines Projekts."""
    by_vector = vector_search(
        connection,
        project_id=project_id,
        query_embedding=embed_query(question, encoder=encoder),
        limit=candidates,
    )
    by_text = text_search(
        connection, project_id=project_id, question=question, limit=candidates
    )

    vector_ids = [chunk.chunk_id for chunk, _ in by_vector]
    text_ids = [chunk.chunk_id for chunk, _ in by_text]
    scores = reciprocal_rank_fusion([vector_ids, text_ids])

    chunks = {chunk.chunk_id: chunk for chunk, _ in [*by_vector, *by_text]}
    ranked = sorted(scores, key=scores.__getitem__, reverse=True)[:limit]
    return [
        SearchHit(
            chunk=chunks[chunk_id],
            score=scores[chunk_id],
            vector_rank=rank_of(chunk_id, vector_ids),
            text_rank=rank_of(chunk_id, text_ids),
        )
        for chunk_id in ranked
    ]


def vector_search(
    connection: psycopg.Connection,
    *,
    project_id: str,
    query_embedding: Sequence[float],
    limit: int,
) -> list[tuple[Chunk, float]]:
    """Nächste Nachbarn nach Cosinus-Ähnlichkeit.

    ``<=>`` ist in pgvector der Cosinus-*Abstand* (0 = gleiche Richtung). Die Ähnlichkeit
    ist ``1 - Abstand``. Ohne Index durchsucht Postgres alle Chunks des Projekts – exakt
    und bei dieser Datenmenge schnell genug.
    """
    rows = connection.execute(
        f"""
        SELECT {SELECT_CHUNK}, 1 - (embedding <=> %(query)s::vector) AS similarity
        FROM chunks
        WHERE project_id = %(project_id)s AND embedding IS NOT NULL
        ORDER BY embedding <=> %(query)s::vector
        LIMIT %(limit)s
        """,
        {"query": list(query_embedding), "project_id": project_id, "limit": limit},
    ).fetchall()
    return [(row_to_chunk(row), float(row[-1])) for row in rows]


def text_search(
    connection: psycopg.Connection,
    *,
    project_id: str,
    question: str,
    limit: int,
) -> list[tuple[Chunk, float]]:
    """Volltextsuche mit deutscher Stammformbildung, Wörter mit ODER verknüpft.

    ``plainto_tsquery`` verknüpft mit UND: Jedes Wort der Frage müsste vorkommen, und
    „Welche Genehmigungen sind offen?“ fände nur Chunks mit „Genehmigung“ *und* „offen“.
    Deshalb wird das UND durch ODER ersetzt; die Rangfolge (``ts_rank_cd``) bevorzugt
    trotzdem Chunks, die mehr Wörter enthalten. Füllwörter wie „welche“ oder „sind“
    entfernt die deutsche Konfiguration vorab.
    """
    rows = connection.execute(
        f"""
        WITH q AS (
            SELECT to_tsquery(
                %(config)s::regconfig,
                replace(plainto_tsquery(%(config)s::regconfig, %(question)s)::text, ' & ', ' | ')
            ) AS query
        )
        SELECT {SELECT_CHUNK}, ts_rank_cd(text_search, q.query) AS rank
        FROM chunks, q
        WHERE project_id = %(project_id)s AND text_search @@ q.query
        ORDER BY rank DESC
        LIMIT %(limit)s
        """,
        {
            "config": TEXT_SEARCH_CONFIG,
            "question": question,
            "project_id": project_id,
            "limit": limit,
        },
    ).fetchall()
    return [(row_to_chunk(row), float(row[-1])) for row in rows]


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[str]], k: int = RRF_K
) -> dict[str, float]:
    """Ranglisten zusammenführen: je Liste ``1 / (k + Rang)`` Punkte, Rang ab 1."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1 / (k + rank)
    return scores


def rank_of(item: str, ranking: list[str]) -> int | None:
    return ranking.index(item) + 1 if item in ranking else None


def row_to_chunk(row: tuple[object, ...]) -> Chunk:
    """Die ersten Spalten einer Ergebniszeile als Chunk lesen."""
    return Chunk.model_validate(dict(zip(CHUNK_COLUMNS, row, strict=False)))
