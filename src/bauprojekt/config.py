"""Konfiguration: Datenpfade und Chunking-Parameter, überschreibbar per Umgebungsvariablen.

Alle Werte an einer Stelle, damit der Wechsel von lokalen Pfaden auf Objektspeicher
später nur hier stattfindet.
"""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = Path(os.environ.get("BAUPROJEKT_DATA_DIR", PROJECT_ROOT / "data"))
RAW_DIR = DATA_DIR / "raw"
"""Originaldokumente, nach Projekt-ID getrennt. Werden nur gelesen, nie verändert."""

PARQUET_DIR = DATA_DIR / "parquet"
GENERATED_DIR = DATA_DIR / "generated"

CHUNK_MAX_CHARS = int(os.environ.get("BAUPROJEKT_CHUNK_MAX_CHARS", "1200"))
"""Obergrenze je Chunk in Zeichen.

Das Embedding-Modell in Phase 2 verarbeitet rund 512 Token je Eingabe; für deutschen
Text entspricht das grob 1200 bis 1800 Zeichen. Der Wert liegt bewusst darunter, damit
in Phase 2 noch Überschrift und Kontext vorangestellt werden können.
"""

CHUNK_OVERLAP_CHARS = int(os.environ.get("BAUPROJEKT_CHUNK_OVERLAP_CHARS", "150"))
"""Überlappung zwischen benachbarten Chunks, damit ein Satz an der Grenze nicht verloren geht."""

DATABASE_URL = os.environ.get(
    "BAUPROJEKT_DATABASE_URL",
    "postgresql://bauprojekt:bauprojekt@localhost:5432/bauprojekt",
)
"""Verbindung zu PostgreSQL. Zugangsdaten nur für die lokale Entwicklungsumgebung."""

EMBEDDING_MODEL = os.environ.get(
    "BAUPROJEKT_EMBEDDING_MODEL", "intfloat/multilingual-e5-base"
)
"""Mehrsprachiges Modell mit guter Qualität für deutsche Fachtexte.

E5-Modelle erwarten Präfixe: ``passage: `` für gespeicherte Texte, ``query: `` für Suchanfragen.
Ohne sie liegen Frage und Antwort im Vektorraum systematisch weiter auseinander.
"""

EMBEDDING_DIM = int(os.environ.get("BAUPROJEKT_EMBEDDING_DIM", "768"))
"""Dimension des Modells. Muss zur Spalte ``vector(n)`` passen; ein Modellwechsel erzwingt neue Embeddings."""

TEXT_SEARCH_CONFIG = os.environ.get("BAUPROJEKT_TEXT_SEARCH_CONFIG", "german")
"""Postgres-Konfiguration für die Volltextsuche (Stemming, Stoppwörter)."""

LLM_MODEL = os.environ.get("BAUPROJEKT_LLM_MODEL", "anthropic:claude-opus-5")
"""Sprachmodell für den Risikobericht, im Format ``anbieter:modell`` von Pydantic AI.

Beispiele: ``anthropic:claude-opus-5`` (braucht ``ANTHROPIC_API_KEY``) oder
``ollama:<modell>`` für ein lokales Modell. Der Anbieterwechsel ist nur diese Zeile.
"""

LLM_RETRIES = int(os.environ.get("BAUPROJEKT_LLM_RETRIES", "2"))
"""Wie oft das Modell eine Antwort mit ungültigen Quellen nachbessern darf, bevor abgebrochen wird."""
