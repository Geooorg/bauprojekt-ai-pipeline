# CLAUDE.md

Lernprojekt für Data Pipelines: Baudokumente (PDFs) einlesen, als Parquet speichern, per Embeddings in pgvector durchsuchbar machen und daraus mit RAG quellenbasierte Risikoberichte erzeugen.

**Es ist ein Lernprojekt.** Erkläre Designentscheidungen kurz, halte Lösungen einfach und nachvollziehbar, und baue keine Abstraktionen auf Vorrat. Lieber eine direkte Implementierung, die man versteht, als ein Framework, das Dinge versteckt.

## Produktvision (Kurzfassung)

Vollständige Beschreibung: [docs/produktvision.md](docs/produktvision.md). **Lies sie, bevor du am Datenmodell, an Dokumenttypen, am Risikomodell oder am Report arbeitest.**

Leitplanken, die immer gelten:

- **Quellenpflicht:** Jede Aussage verweist auf Dokument, Version, Seite/Abschnitt und Textauszug.
- **Fakten ≠ Schlussfolgerungen ≠ Unsicherheiten** – im Report und im Datenmodell getrennt halten.
- **Originale bleiben unverändert** erhalten; Verarbeitung erzeugt nur abgeleitete Daten.
- **Projektisolation:** Jedes Dokument gehört genau einem Projekt; Suche und Analyse dürfen Projektgrenzen nie überschreiten.
- **Versionen unterscheidbar** (z. B. über Inhalts-Hash); Verarbeitung **inkrementell** – bereits verarbeitete Versionen überspringen.
- **Risiko-Pflichtfelder:** Titel, Kategorie, Beschreibung, Projektbereich, Auswirkung, Wahrscheinlichkeit, Schweregrad, Verantwortlicher, Maßnahme, Status, Quellenbelege.
- **Risikokategorien:** Termin, Kosten, Genehmigung, Planung, Qualität, Vertrag, Ressourcen, Lieferanten, Schnittstellen.

**Scope Prototyp:** ein fiktives Bauprojekt, PDF + DOCX, Fokus auf Gesprächsprotokolle, Statusberichte, Terminpläne und Genehmigungsunterlagen. Weitere Dokumentarten erst später – aber so bauen, dass neue Typen ergänzt werden können, ohne Bestehendes umzubauen.

## Ziel-Architektur

```
                 bauprojekt-ai-pipeline
                         |
        +----------------+----------------+
        |                |                |
        v                v                v
   document-worker  embedding-worker  report-api
        |                |                |
        v                v                v
     PyMuPDF        Sentence         FastAPI
     Tika           Transformers
        |                |                |
        v                v                v
     Parquet       pgvector          RAG / LLM
        |                |                |
        +----------------+----------------+
                         |
                         v
                 PostgreSQL
              + RabbitMQ + MinIO
```

Die Architektur ist das Ziel, nicht der Startpunkt. RabbitMQ, MinIO und die Aufteilung in getrennte Worker kommen erst dazu, wenn die jeweilige Phase lokal funktioniert.

### Sprachmodell als eigener Dienst

Entschieden am 19.09.2026, Phase 3.

- **Das LLM ist ein eigener Dienst hinter einer HTTP-Schnittstelle.** Es läuft nicht in unseren Python-Prozessen oder -Containern. Der Code kennt nur `BAUPROJEKT_LLM_MODEL` (`anbieter:modell`) und bei lokalen Modellen die Basis-URL. Der Anbieter wechselt per Konfiguration, nicht per Code.
- **Abstraktion: Pydantic AI** (`pydantic-ai-slim` mit den Extras der genutzten Anbieter). Ausgabe als Pydantic-Modell (`risks.py`). Tests ohne Netz über `TestModel` und `FunctionModel`.
- **Quellen prüft der Code, nicht der Anbieter.** Das Modell nennt `chunk_id` und wörtlichen Auszug, `report.check_sources` prüft beides. Anbieterspezifische Zitierfunktionen werden nicht genutzt. Deshalb kostet die Abstraktion hier nichts.
- **Entwicklung (Mac): Ollama nativ, nicht im Container.**
  - Podman-Container laufen in einer Linux-VM (`applehv`, 8 GiB) ohne Zugriff auf die Metal-GPU. Ein Modell liefe dort nur auf der CPU und passte nicht in den Speicher.
  - Natives Ollama läuft auf Port **11435**, weil 11434 von einem fremden Container (`cockpit-ollama-1`) belegt ist.
  - Einrichtung und Speicherorte: [README.md](README.md#sprachmodell-lokal-phase-3).
- **Produktion (Linux mit NVIDIA): LLM als Container ist der Normalfall.** Etwa vLLM mit GPU über das NVIDIA Container Toolkit bzw. in Kubernetes über den GPU Operator. Die Schnittstelle bleibt gleich (OpenAI-kompatibel).
- **Kein LLM-Dienst in `infra/docker-compose.yml`.**
- **Modelle werden anhand der bekannten Wahrheit ([docs/testdaten.md](docs/testdaten.md)) verglichen**, mit `scripts/evaluate_report.py`, nicht nach Eindruck.

## Phasen

Arbeite phasenweise. Beginne keine neue Phase, bevor das Ergebnis der aktuellen erreicht und getestet ist.

### Phase 1 – Dokumente → Parquet
- Ziel: Dokumente einlesen und strukturiert speichern.
- Stack: uv, Python, PyMuPDF, Polars, PyArrow, Parquet, pytest (DuckDB zum Abfragen der Parquet-Dateien).
- Ergebnis: 20 PDFs einlesen und die extrahierten Chunks als Parquet-Datei speichern.
- Designentscheidung: Parquet nicht als Ersatz für PostgreSQL verwenden, sondern als Data-Lake-/Analytics-Schicht zwischen Dokumentverarbeitung und Embedding-/Analyseprozessen.

### Phase 2 – Parquet → Embeddings → pgvector
- Ziel: Semantische Suche auf den Dokumenten.
- Stack: Sentence Transformers, PostgreSQL + pgvector, psycopg, Cosine Similarity, Hybrid Search (Vektor + Volltext).
- Ergebnis: „Welche Genehmigungen sind offen?" liefert die passenden Textstellen.

### Phase 3 – RAG + Risikomanagement
- Ziel: Einen quellenbasierten Report erzeugen.
- Stack: LlamaIndex oder direkte Implementierung, LLM, Pydantic, FastAPI, strukturierte Report-Ausgabe.
- Ergebnis: „Erstelle den Risikobericht für BAU-42." liefert Risiken mit Begründung, Maßnahmen und Originalquellen.

## Projektstruktur (Phase 1)

```
src/bauprojekt/        # Paket (src-Layout, gebaut mit uv_build)
├── config.py          # Pfade, Chunk-Größe (Umgebungsvariablen)
├── models.py          # Pydantic-Modelle Document, Segment, Chunk + Polars-Schemas
├── extraction.py      # extract_pdf, extract_docx – reine Funktionen
├── chunking.py        # chunk_segments – reine Funktionen
└── pipeline.py        # Orchestrierung: lesen, hashen, bekannte Versionen überspringen, Parquet schreiben
scripts/               # dünne CLIs, rufen nur das Paket auf
├── generate_sample_documents.py   # synthetische Projekte BAU-42 / BAU-43
└── ingest_documents.py
tests/                 # pytest; kleine Beispieldateien in tests/fixtures/
data/                  # nicht versioniert (nur .gitkeep)
├── raw/<projekt-id>/  # Originale – nie verändern
├── parquet/           # documents.parquet, segments.parquet, chunks.parquet
└── generated/         # Reports (später)
```

Module für spätere Phasen (`embeddings.py`, `search.py` …) werden erst in der jeweiligen Phase angelegt.

**Testdaten:** `data/raw/BAU-42` enthält bewusst eingebaute Sachverhalte, `BAU-43` dient als Kontrollprojekt für die Trennung der Projekte. Welche Sachverhalte wo stehen, beschreibt [docs/testdaten.md](docs/testdaten.md). Diese Datei ist der Maßstab für Tests und Auswertungen und muss bei Änderungen am Generator mitgepflegt werden.

## Konventionen

- **Chunks tragen immer ihre Herkunft** (Projekt-ID wie `BAU-42`, Dokument, Version, Seite/Abschnitt, Chunk-Index). Ohne Quelle keine Quellenverweise in Phase 3.
- Datenschemata explizit festlegen (Polars-Schema bzw. Pydantic-Modelle), nicht implizit ableiten lassen.
- Rohdaten, Zwischenstände und Parquet-Ausgaben gehören nicht ins Git (`data/` o. ä. in `.gitignore`).
- Konfiguration (DB-URL, Zugangsdaten, Modellnamen) über Umgebungsvariablen, nicht hart kodieren.
- Typannotationen überall; Code muss `ruff` und `mypy` bestehen.
- Tests mit pytest; kleine Beispiel-PDFs als Fixtures statt echter Projektdokumente.

## Tooling

Paketverwaltung ausschließlich mit **uv** – kein `pip`, kein manuelles venv.

```bash
uv sync                      # Abhängigkeiten installieren
uv add <paket>               # Abhängigkeit hinzufügen
uv add --dev <paket>         # Dev-Abhängigkeit hinzufügen
uv run pytest                # Tests
uv run ruff check .          # Linting
uv run ruff format .         # Formatierung
uv run mypy .                # Typprüfung
```

Python-Version: siehe `.python-version` (aktuell 3.14).

## Infrastruktur

**Auf diesem Rechner ist nur Podman installiert, kein Docker.** Nie `docker` oder `docker compose` verwenden.

```bash
podman compose -f infra/docker-compose.yml up -d     # Dienste starten
podman compose -f infra/docker-compose.yml ps        # Status
podman compose -f infra/docker-compose.yml logs -f postgres
podman compose -f infra/docker-compose.yml down      # stoppen (Volumes bleiben)
```

Falls `podman compose` nicht funktioniert: `podman machine start` prüfen bzw. `podman-compose` nutzen.

| Dienst     | Image                    | Ports                         | Zugang (nur lokal)            |
|------------|--------------------------|-------------------------------|-------------------------------|
| PostgreSQL | `pgvector/pgvector:pg17` | 5432                          | DB/User/Passwort `bauprojekt` |
| RabbitMQ   | `rabbitmq:4-management`  | 5672, UI 15672                | `bauprojekt` / `bauprojekt`   |
| MinIO      | `quay.io/minio/minio`    | API 9000, Konsole 9001        | `bauprojekt` / `change-me-local` |

Die pgvector-Extension muss pro Datenbank aktiviert werden: `CREATE EXTENSION IF NOT EXISTS vector;`

Die Zugangsdaten sind reine Entwicklungswerte – nie für etwas anderes als die lokale Umgebung verwenden.
