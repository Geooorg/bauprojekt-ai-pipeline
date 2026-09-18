# bauprojekt-ai-pipeline

Lernprojekt: Baudokumente einlesen, als Parquet speichern, semantisch durchsuchen und quellenbasierte Risikoberichte erzeugen.

- Produktvision: [docs/produktvision.md](docs/produktvision.md)
- Testdaten und die bekannte Wahrheit dazu: [docs/testdaten.md](docs/testdaten.md)
- Arbeitsregeln, Phasen und Konventionen: [CLAUDE.md](CLAUDE.md)
- Schnittstellen und Nachweis der Projekttrennung: [docs/spezifikation.md](docs/spezifikation.md)
- Suchkomponente: [docs/postgres-vs-elasticsearch.md](docs/postgres-vs-elasticsearch.md)

## Voraussetzungen

| Werkzeug | Zweck | Prüfen mit |
|---|---|---|
| [uv](https://docs.astral.sh/uv/) | Paket- und Python-Verwaltung (kein `pip`, kein manuelles venv) | `uv --version` |
| Python 3.14 | wird von uv installiert, siehe `.python-version` | `uv python list` |
| Podman | PostgreSQL, RabbitMQ, MinIO lokal. **Docker ist auf diesem Rechner nicht installiert.** | `podman machine list` |

## Schnellstart

```bash
uv sync
```

Das installiert alle Abhängigkeiten und das Projekt selbst, sodass `import bauprojekt` funktioniert.

```bash
uv run python scripts/generate_sample_documents.py
```

Erzeugt die synthetischen Projekte **BAU-42** (8 Dokumente mit bewusst eingebauten Sachverhalten) und **BAU-43** (Kontrollprojekt für die Projekttrennung) unter `data/raw/`. Die Ausgabe ist reproduzierbar: Gleicher Inhalt ergibt denselben Hash, ein erneuter Aufruf legt also keine neuen Versionen an.

```bash
uv run python scripts/ingest_documents.py
```

Liest alle Dokumente ein und schreibt `documents.parquet`, `segments.parquet` und `chunks.parquet` nach `data/parquet/`.

```bash
uv run python scripts/query_parquet.py --beispiele
```

Führt vorbereitete DuckDB-Abfragen auf dem Ergebnis aus.

## Dokumente einlesen

Der Durchlauf ist **inkrementell**: Bereits bekannte Dokumentversionen werden übersprungen. Die Identität eines Dokuments umfasst Projekt, Pfad und Inhalts-Hash. Geänderter Inhalt ergibt also eine neue Version, die alte bleibt erhalten.

```bash
uv run python scripts/ingest_documents.py                    # alle Projekte
uv run python scripts/ingest_documents.py --project BAU-42   # nur ein Projekt
uv run python scripts/ingest_documents.py --raw-dir /pfad --parquet-dir /pfad
```

Ausgabe eines zweiten Durchlaufs ohne neue Dokumente:

```
0 Dokumente verarbeitet, 11 übersprungen (bereits bekannt), 0 Segmente, 0 Chunks.
```

**Eigene Dokumente einlesen.** Die Ablage bestimmt Projektzuordnung und Dokumentart:

```
data/raw/<PROJEKT-ID>/<ordner>/<datei>
```

- `<PROJEKT-ID>` wird die `project_id`, z. B. `BAU-42`. Format: 2–10 Großbuchstaben, Bindestrich, 1–6 Ziffern. Dateien, die nicht in einem solchen Ordner liegen, werden **abgewiesen** und am Ende des Laufs aufgelistet; die übrigen werden trotzdem eingelesen.
- `<ordner>` bestimmt die Dokumentart: `protokolle`, `statusberichte`, `terminplan`, `genehmigungen`. Alles andere wird `unbekannt`.
- Unterstützt werden `.pdf`, `.docx` und `.xlsx`. Andere Dateien werden stillschweigend übergangen.
- Ein Datum im Dateinamen (`2026-09-15_...` oder `..._2026-09`) wird als `document_date` übernommen. Es ordnet Aussagen zeitlich ein und unterscheidet aktuelle von überholten.

**Alles neu aufbauen**, etwa nach einer Änderung an Extraktion oder Chunking:

```bash
rm -f data/parquet/*.parquet && uv run python scripts/ingest_documents.py
```

Die Originale unter `data/raw/` werden dabei nie verändert.

## Daten abfragen (DuckDB)

Die Sichten heißen `documents`, `segments` und `chunks`.

```bash
uv run python scripts/query_parquet.py "SELECT project_id, count(*) FROM chunks GROUP BY 1"
uv run python scripts/query_parquet.py --datei meine_abfrage.sql
uv run python scripts/query_parquet.py --beispiele
```

Die Beispiele in [scripts/query_parquet.py](scripts/query_parquet.py) zeigen typische Auswertungen: offene Punkte, ungeklärte Verantwortlichkeiten, zeitliche Entwicklung eines Themas, Prüfung der Projekttrennung.

## Infrastruktur starten (ab Phase 2)

```bash
podman compose -f infra/docker-compose.yml up -d        # alle Dienste
podman compose -f infra/docker-compose.yml up -d postgres
podman compose -f infra/docker-compose.yml ps
podman compose -f infra/docker-compose.yml down         # stoppen, Daten bleiben erhalten
```

| Dienst | Ports | Zugang (nur lokal) |
|---|---|---|
| PostgreSQL + pgvector | 5432 | `bauprojekt` / `bauprojekt` / DB `bauprojekt` |
| RabbitMQ | 5672, Oberfläche 15672 | `bauprojekt` / `bauprojekt` |
| MinIO | 9000, Konsole 9001 | `bauprojekt` / `change-me-local` |

Das Schema legt `bauprojekt.db.init_schema()` an, inklusive `CREATE EXTENSION vector`. Direkter Zugriff auf die Datenbank:

```bash
podman exec -it bauprojekt-postgres psql -U bauprojekt -d bauprojekt
```

## Suchen (Phase 2)

Voraussetzung: Postgres läuft, die Dokumente sind eingelesen.

```bash
uv run python scripts/embed_chunks.py                  # Chunks einbetten und nach Postgres schreiben
uv run python scripts/embed_chunks.py --project BAU-42
```

Nur Chunks, die noch nicht in der Datenbank stehen, werden eingebettet. Nach einer Änderung am Tabellenaufbau meldet das Skript das selbst und verlangt `--neu`. Nach einem Neuaufbau von Parquet (geänderte Extraktion oder Chunking) haben geänderte Chunks neue IDs und werden neu berechnet. Veraltete Einträge bleiben dabei in der Tabelle stehen; für einen sauberen Neuaufbau:

```bash
podman exec bauprojekt-postgres psql -U bauprojekt -d bauprojekt -c "TRUNCATE chunks"
uv run python scripts/embed_chunks.py
```

Suchen – die Projekt-ID ist Pflicht, eine projektübergreifende Suche gibt es bewusst nicht:

```bash
uv run python scripts/search_documents.py BAU-42 "Welche Genehmigungen sind offen?"
uv run python scripts/search_documents.py BAU-42 "Nachtrag N-07" --limit 3 --volltext
```

Jeder Treffer zeigt Quelle, Punktzahl und den Rang in Vektor- und Volltextsuche. So ist nachvollziehbar, welches Verfahren ihn gefunden hat.

Suchqualität gegen die bekannte Wahrheit aus [docs/testdaten.md](docs/testdaten.md) messen:

```bash
uv run python scripts/evaluate_search.py --k 5
uv run python scripts/evaluate_search.py --k 10 --details
```

Gemessen wird der Recall@k je Frage, getrennt für Vektor-, Volltext- und Hybrid-Suche. Das ist der Maßstab für jede Änderung an Chunking, Modell oder Suche: erst messen, dann ändern, dann wieder messen.

## Tests

```bash
uv run pytest                   # alles
uv run pytest -m "not db"       # ohne Datenbanktests
uv run pytest tests/test_chunking.py -vv
uv run pytest -k brandschutz
```

Die mit `db` markierten Tests brauchen eine laufende PostgreSQL-Instanz. Sie arbeiten in einem eigenen Schema, das anschließend wieder gelöscht wird, und werden ohne Datenbank übersprungen. Vorhandene Daten bleiben unberührt.

Vor jedem Commit:

```bash
uv run ruff format . && uv run ruff check . && uv run mypy src tests scripts && uv run pytest
```

## Abhängigkeiten mit Besonderheiten

- **`compound-split`** (Komposita-Zerlegung) steht unter **GPL-3.0**. Für ein privates Lernprojekt ohne Weitergabe ist das unproblematisch. Bei einer Weitergabe der Software gälte die GPL für das Gesamtwerk. Das Paket wird nur in `compounds.py` verwendet und ließe sich dort ersetzen, etwa durch Hunspell-Wörterbücher in Postgres.
- **`sentence-transformers`** bringt PyTorch mit (rund 560 MB). Geladen wird es nur beim Einbetten, nicht in den Tests.

## Konfiguration

Alle Werte stehen in [src/bauprojekt/config.py](src/bauprojekt/config.py) und lassen sich über Umgebungsvariablen überschreiben:

| Variable | Vorgabe | Bedeutung |
|---|---|---|
| `BAUPROJEKT_DATA_DIR` | `<projekt>/data` | Wurzel für `raw/`, `parquet/`, `generated/` |
| `BAUPROJEKT_CHUNK_MAX_CHARS` | `1200` | Obergrenze je Chunk |
| `BAUPROJEKT_CHUNK_OVERLAP_CHARS` | `150` | Überlappung benachbarter Chunks |
| `BAUPROJEKT_DATABASE_URL` | `postgresql://bauprojekt:bauprojekt@localhost:5432/bauprojekt` | Datenbankverbindung |
| `BAUPROJEKT_EMBEDDING_MODEL` | `intfloat/multilingual-e5-base` | Embedding-Modell (ca. 1,1 GB beim ersten Laden) |
| `BAUPROJEKT_EMBEDDING_DIM` | `768` | Muss zum Modell **und** zur Spalte `vector(n)` passen |
| `BAUPROJEKT_TEXT_SEARCH_CONFIG` | `german` | Konfiguration der Volltextsuche in Postgres |

Ein Wechsel des Embedding-Modells erzwingt neue Embeddings für alle Chunks und in der Regel ein neues Tabellenschema.

## Aufbau

```
src/bauprojekt/
├── config.py        # Pfade, Chunk-Parameter, Datenbank, Modell
├── models.py        # Document, Segment, Chunk + Polars-Schemas
├── extraction.py    # PDF, DOCX, XLSX → Segmente (reine Funktionen auf Bytes)
├── chunking.py      # Segmente → Chunks (reine Funktionen)
├── pipeline.py      # einziger Ort mit Dateisystemzugriff
├── db.py            # PostgreSQL + pgvector: Schema und Schreibzugriff
├── embeddings.py    # Texte und Fragen → Vektoren
├── compounds.py     # Komposita zerlegen für die Volltextsuche (Baugenehmigung → bau, genehmigung)
└── search.py        # Hybrid-Suche: Vektor + Volltext, Reciprocal Rank Fusion
```

Der Datenfluss: `data/raw` → `extraction` → `chunking` → `data/parquet` → `embeddings` → PostgreSQL → `search`.

Sequenzdiagramme (PlantUML): [docs/diagrams/pipeline.puml](docs/diagrams/pipeline.puml) für Einlesen und Einbetten, [docs/diagrams/search.puml](docs/diagrams/search.puml) für die Hybrid-Suche.

Zwei Regeln erklären die meisten Entwurfsentscheidungen:

1. **Jeder Chunk trägt seine Herkunft** (Projekt, Dokument, Version, Seite oder Abschnitt, Zeichenposition). Ein Treffer ist dadurch allein zitierfähig, ohne Verknüpfung mit anderen Tabellen.
2. **Ein Filter auf `project_id` genügt**, um Projekte zu trennen. Deshalb stehen die Herkunftsfelder redundant im Chunk.

## Wenn etwas klemmt

| Problem | Ursache und Lösung |
|---|---|
| `ModuleNotFoundError: bauprojekt` | `uv sync` ausführen; das Paket wird dabei installiert. |
| `Keine Datenbank erreichbar` beim Test | Postgres starten, oder `uv run pytest -m "not db"`. |
| `podman compose` schlägt fehl | `podman machine start` prüfen. |
| `denied: requested access to the resource is denied` beim Abrufen von MinIO | Das Image liegt nicht mehr auf Docker Hub; die Compose-Datei verweist auf `quay.io/minio/minio`. |
| Extraktion liefert unerwartete Segmente | Mit DuckDB direkt in `segments` schauen (Dateiname steht in `documents`): `SELECT s.locator, s.heading, substr(s.text,1,200) FROM segments s JOIN documents d USING (document_id) WHERE d.file_name = '…'` |
| `Tabelle chunks ist veraltet (fehlt: …)` | Der Tabellenaufbau hat sich geändert: `uv run python scripts/embed_chunks.py --neu`. Unbedenklich, die Quelle bleibt Parquet. |
| `Modell liefert Dimension … erwartet …` | `BAUPROJEKT_EMBEDDING_DIM` passt nicht zum Modell oder zur Tabellenspalte. |
