"""Chunks und Fragen in Vektoren übersetzen.

Zwei Eigenheiten des Modells bestimmen dieses Modul:

1. **Präfixe.** E5-Modelle sind darauf trainiert, gespeicherte Texte mit ``passage: `` und
   Suchanfragen mit ``query: `` zu kennzeichnen. Fehlen sie, funktioniert die Suche
   scheinbar, liefert aber systematisch schlechtere Treffer – ein Fehler, der ohne
   Fehlermeldung bleibt.
2. **Kontext.** Der Überschrift wird dem Text nur *für die Einbettung* vorangestellt.
   ``chunk.text`` bleibt wortgleich zum Dokument, damit Zitate und die Zeichenpositionen
   weiter stimmen.

Das Modell wird als ``encoder`` hereingereicht. Dadurch laufen die Tests ohne Modell, und
ein Wechsel des Modells berührt nur ``load_encoder``.
"""

from collections.abc import Sequence
from typing import Protocol

from bauprojekt.config import EMBEDDING_DIM, EMBEDDING_MODEL
from bauprojekt.models import Chunk

PASSAGE_PREFIX = "passage: "
QUERY_PREFIX = "query: "
DEFAULT_BATCH_SIZE = 32

Embedding = list[float]


class Encoder(Protocol):
    """Was dieses Modul vom Modell braucht – mehr nicht."""

    def encode(self, texts: list[str]) -> Sequence[Sequence[float]]: ...


def load_encoder(model_name: str = EMBEDDING_MODEL) -> Encoder:
    """Modell laden. Der Import liegt in der Funktion, damit Tests ohne Torch auskommen."""
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(model_name)

    class NormalizedEncoder:
        """Normalisierte Vektoren: Damit entspricht Cosinus-Ähnlichkeit dem Skalarprodukt."""

        def encode(self, texts: list[str]) -> Sequence[Sequence[float]]:
            return model.encode(texts, normalize_embeddings=True).tolist()

    return NormalizedEncoder()


def passage_text(chunk: Chunk) -> str:
    """Eingabetext für die Einbettung: Präfix, Überschrift als Kontext, dann der Chunk-Text."""
    if chunk.heading:
        return f"{PASSAGE_PREFIX}{chunk.heading}\n{chunk.text}"
    return f"{PASSAGE_PREFIX}{chunk.text}"


def query_text(question: str) -> str:
    """Eingabetext für eine Suchanfrage."""
    return f"{QUERY_PREFIX}{question.strip()}"


def embed_chunks(
    chunks: Sequence[Chunk],
    *,
    encoder: Encoder,
    batch_size: int = DEFAULT_BATCH_SIZE,
    expected_dim: int = EMBEDDING_DIM,
) -> list[tuple[Chunk, Embedding]]:
    """Chunks stapelweise einbetten und mit ihrem Vektor paaren."""
    pairs: list[tuple[Chunk, Embedding]] = []
    for start in range(0, len(chunks), batch_size):
        batch = list(chunks[start : start + batch_size])
        vectors = encoder.encode([passage_text(chunk) for chunk in batch])
        for chunk, vector in zip(batch, vectors, strict=True):
            pairs.append((chunk, check_dimension(vector, expected_dim)))
    return pairs


def embed_query(
    question: str, *, encoder: Encoder, expected_dim: int = EMBEDDING_DIM
) -> Embedding:
    """Eine Frage in denselben Vektorraum übersetzen wie die gespeicherten Texte."""
    vectors = encoder.encode([query_text(question)])
    return check_dimension(vectors[0], expected_dim)


def check_dimension(vector: Sequence[float], expected_dim: int) -> Embedding:
    """Früh prüfen: Ein Modellwechsel fällt sonst erst beim Schreiben in die Datenbank auf."""
    if len(vector) != expected_dim:
        raise ValueError(
            f"Modell liefert Dimension {len(vector)}, erwartet {expected_dim}. "
            "Passt BAUPROJEKT_EMBEDDING_DIM zum Modell? Ein Wechsel erzwingt neue Embeddings."
        )
    return list(vector)
