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
