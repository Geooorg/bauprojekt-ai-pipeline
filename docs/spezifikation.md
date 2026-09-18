# Spezifikation: Schnittstellen und Projekttrennung

Stand: Phase 2 abgeschlossen (Commit nach `7eed50b`). Die Signaturen sind aus dem Code gelesen (`inspect.signature`), nicht abgeschrieben. Ablaufdiagramme: [diagrams/pipeline.puml](diagrams/pipeline.puml), [diagrams/search.puml](diagrams/search.puml).

Das Dokument hat zwei Teile:

1. **Schnittstellen** – was hineingeht, was gesucht wird, was herauskommt.
2. **Projekttrennung** – wie Daten verschiedener Projekte (Kunden) im Code getrennt werden, belegt durch Code-Stellen und Tests. Dazu gehören die Grenzen, die heute noch bestehen.

---

## Teil 1: Schnittstellen

### 1.1 Datenmodelle (`bauprojekt.models`)

Alle Modelle sind unveränderlich (`frozen=True`) und lehnen unbekannte Felder ab (`extra="forbid"`). `project_id` hat in allen Modellen den Typ `ProjectId`: eine Zeichenkette, die beim Erzeugen gegen `PROJECT_ID_PATTERN` = `[A-Z]{2,10}-[0-9]{1,6}` geprüft wird.

| Modell | Felder |
|---|---|
| `Document` | `document_id: str`, `content_hash: str`, **`project_id: str`**, `source_path: str`, `file_name: str`, `doc_type: DocType`, `media_type: str`, `file_size: int`, `document_date: date \| None`, `ingested_at: datetime` |
| `Segment` | `segment_id: str`, `document_id: str`, **`project_id: str`**, `index: int`, `kind: SegmentKind`, `page_no: int \| None`, `locator: str`, `heading: str \| None`, `text: str` |
| `Chunk` | `chunk_id: str`, `segment_id: str`, `document_id: str`, **`project_id: str`**, `index: int`, `text: str`, `char_start: int`, `char_end: int`, `source_path: str`, `file_name: str`, `doc_type: DocType`, `document_date: date \| None`, `page_no: int \| None`, `locator: str`, `heading: str \| None` |
| `SearchHit` (`bauprojekt.search`) | `chunk: Chunk`, `score: float`, `vector_rank: int \| None`, `text_rank: int \| None` |

Erzeugt werden die Modelle nur über Fabrikmethoden. Diese übernehmen `project_id` vom übergeordneten Objekt:

```python
Document.from_file(path: Path, *, project_id: str, raw_root: Path, doc_type: DocType,
                   media_type: str, document_date: date | None, ingested_at: datetime) -> Document
Segment.create(*, document: Document, index: int, kind: SegmentKind, locator: str, text: str,
               page_no: int | None = None, heading: str | None = None) -> Segment
Chunk.create(*, document: Document, segment: Segment, index: int, text: str,
             char_start: int, char_end: int) -> Chunk
Chunk.citation() -> str   # "BAU-42 · statusbericht_2026-09.pdf · S. 2 · 01.09.2026"
```

`Segment.create` und `Chunk.create` haben **keinen** Parameter `project_id`. Die Zuordnung lässt sich auf dieser Ebene also nicht versehentlich ändern.

### 1.2 Eingaben: Einlesen (`bauprojekt.pipeline`, Phase 1)

```python
ingest(*, raw_dir: Path = RAW_DIR, parquet_dir: Path = PARQUET_DIR,
       project_id: str | None = None, now: datetime | None = None) -> IngestResult
# IngestResult(documents: int, skipped: int, segments: int, chunks: int, rejected: list[str])
# ValueError, wenn project_id angegeben ist und nicht dem Format entspricht
```

| Eingabe | Herkunft | Regel |
|---|---|---|
| Datei | `data/raw/<PROJEKT-ID>/<ordner>/<datei>` | nur `.pdf`, `.docx`, `.xlsx`; andere werden übergangen |
| `project_id` | **erster Ordner** unter `raw_dir` | Format `PROJECT_ID_PATTERN` (`BAU-42`); ungültig oder fehlend → Datei abgewiesen (`IngestResult.rejected`) |
| `doc_type` | Unterordner | `protokolle`, `statusberichte`, `terminplan`, `genehmigungen`, sonst `unbekannt` |
| `document_date` | Datum im Dateinamen | `2026-09-15` oder `2026-09` (→ Monatserster) |
| Parameter `project_id` | Aufrufer | schränkt die **Suche nach Dateien** auf `raw_dir/<project_id>` ein |

Reine Verarbeitungsfunktionen, ohne Dateisystemzugriff:

```python
extraction.extract(document: Document, data: bytes) -> list[Segment]
chunking.chunk_segments(document: Document, segments: list[Segment], *,
                        max_chars: int = 1200, overlap: int = 150) -> list[Chunk]
```

Ausgabe: `data/parquet/documents.parquet`, `segments.parquet` und `chunks.parquet` mit festem Polars-Schema (`models.SCHEMAS`). Alle Projekte liegen in denselben drei Dateien.

### 1.3 Eingaben: Einbetten (`bauprojekt.pipeline`, `embeddings`, `db`, Phase 2)

```python
index_chunks(*, connection: psycopg.Connection, encoder: Encoder,
             parquet_dir: Path = PARQUET_DIR, project_id: str | None = None,
             batch_size: int = 32) -> IndexResult
# IndexResult(embedded: int, skipped: int)

embeddings.load_encoder(model_name: str = "intfloat/multilingual-e5-base") -> Encoder
embeddings.embed_chunks(chunks: Sequence[Chunk], *, encoder: Encoder, batch_size: int = 32,
                        expected_dim: int = 768) -> list[tuple[Chunk, list[float]]]
embeddings.passage_text(chunk: Chunk) -> str        # "passage: <Überschrift>\n<Text>"

db.connect(url: str = DATABASE_URL) -> psycopg.Connection
db.init_schema(connection) -> None                  # RuntimeError bei veralteter Tabelle
db.reset_schema(connection) -> None                 # DROP TABLE chunks
db.upsert_chunks(connection, items: Sequence[tuple[Chunk, Sequence[float]]]) -> int
db.fetch_known_chunk_ids(connection, *, project_id: str | None = None) -> set[str]
```

Tabelle `chunks`: alle Felder von `Chunk`, dazu `compound_terms text`, `embedding vector(768)` und die berechnete Spalte `text_search tsvector`. Primärschlüssel ist `chunk_id`. Indizes gibt es auf `project_id`, `document_id` und `text_search` (GIN).

### 1.4 Suchen (`bauprojekt.search`)

```python
search(connection, *, project_id: str, question: str, encoder: Encoder,
       limit: int = 10, candidates: int = 30) -> list[SearchHit]

vector_search(connection, *, project_id: str, query_embedding: Sequence[float],
              limit: int) -> list[tuple[Chunk, float]]      # float = Cosinus-Ähnlichkeit
text_search(connection, *, project_id: str, question: str,
            limit: int) -> list[tuple[Chunk, float]]        # float = ts_rank_cd

reciprocal_rank_fusion(rankings: Sequence[Sequence[str]], k: int = 60) -> dict[str, float]
embeddings.embed_query(question: str, *, encoder: Encoder, expected_dim: int = 768) -> list[float]
compounds.compound_parts(text: str) -> str
```

Ablauf: Vektorsuche und Volltextsuche liefern je bis zu `candidates` Treffer. `reciprocal_rank_fusion` führt sie zusammen, `search` gibt die besten `limit` zurück (Diagramm: [diagrams/search.puml](diagrams/search.puml)).

### 1.5 Ausgaben

| Ausgabe | Form | Zitierfähigkeit |
|---|---|---|
| `SearchHit` | `Chunk` + Punkte + Rang je Verfahren | `hit.chunk.citation()` → Projekt · Datei · Fundstelle · Datum |
| Textausschnitt | `chunk.text`, wortgleich zum Dokument (nach NFKC) | `char_start`/`char_end` zeigen in den Segmenttext |
| Kommandozeile | `scripts/search_documents.py <PROJEKT> "<Frage>"` | Quelle je Treffer |

### 1.6 Kommandozeile

| Skript | Projektbezug |
|---|---|
| `ingest_documents.py [--project ID]` | optional, sonst alle |
| `embed_chunks.py [--project ID] [--neu]` | optional, sonst alle |
| `search_documents.py PROJEKT "Frage"` | **Pflicht** (Positionsargument) |
| `evaluate_search.py` | je Testfrage fest hinterlegt |
| `query_parquet.py "SQL"` | **keiner**, freies SQL auf allen Projekten (Entwicklerwerkzeug) |

---

## Teil 2: Projekttrennung

### 2.1 Grundsatz

Die Trennung ist heute **logisch, nicht physisch**. Alle Projekte liegen in denselben Parquet-Dateien und derselben Tabelle `chunks`. Getrennt wird über das Feld `project_id`. Dieses Feld steht in jedem Datensatz, wird nur an einer Stelle gesetzt und in jeder Suchabfrage als Bedingung verlangt.

### 2.2 Zusicherungen, Mechanismus und Nachweis

| # | Zusicherung | Mechanismus | Code-Stelle | Test |
|---|---|---|---|---|
| T1 | Jedes Dokument gehört genau einem Projekt. | `project_id` = erster Ordner unter `raw_dir`, Pflichtfeld ohne Vorgabe | `pipeline.build_document`, `models.Document` | `test_pipeline.py::TestProjekttrennung::test_jedes_dokument_traegt_sein_projekt` |
| T2 | Die Zuordnung vererbt sich unverändert. | Fabrikmethoden übernehmen `project_id` vom übergeordneten Objekt; kein eigener Parameter | `Segment.create`, `Chunk.create` | `test_extraction.py::…::test_projektzuordnung_wird_durchgereicht`, `test_chunking.py::…::test_projekt_und_dokumentangaben_werden_durchgereicht` |
| T3 | Gleicher Inhalt in zwei Projekten ergibt zwei getrennte Dokumente. | `document_id = derive_id(project_id, source_path, content_hash)` | `models.Document.from_file` | `test_models.py::…::test_gleicher_inhalt_in_zwei_projekten_bleibt_getrennt` |
| T4 | Chunk-IDs verschiedener Projekte können nicht kollidieren. | `segment_id` leitet sich aus `document_id` ab, `chunk_id` aus `segment_id`, das Projekt steckt also in jeder ID. Upsert auf `chunk_id` kann keinen fremden Datensatz überschreiben. | `models.derive_id`, `db.upsert_chunks` | indirekt über T3 und `test_db.py::TestProjekttrennung` |
| T5 | Jeder Datensatz ist nach Projekt filterbar. | `project_id text NOT NULL` in der Tabelle, Index `chunks_project_idx` | `db.init_schema` | `test_db.py::TestSchema::test_tabelle_und_spalten_existieren` |
| T6 | **Eine Suche über mehrere Projekte ist nicht formulierbar.** | `project_id: str` ist in `search`, `vector_search` und `text_search` ein Pflichtargument ohne Vorgabewert. Fehlt es, bricht der Aufruf mit `TypeError` ab. | `search.py` | mypy (Typprüfung) und die Signaturen |
| T7 | Beide Suchverfahren filtern in SQL. | `WHERE project_id = %(project_id)s` in beiden Abfragen; Parameterbindung, keine String-Verkettung | `search.vector_search`, `search.text_search` | `test_search.py::TestProjekttrennung::test_gleicher_vektor_anderes_projekt_bleibt_draussen` |
| T8 | Die Zusammenführung mischt keine Projekte. | `reciprocal_rank_fusion` erhält nur die bereits gefilterten Listen | `search.search` | `test_search.py::TestProjekttrennung::test_anderes_projekt_findet_nur_seins` |
| T9 | Ein unbekanntes Projekt liefert nichts statt alles. | Filter auf nicht existierenden Wert ergibt eine leere Menge | `search.py` | `test_search.py::TestProjekttrennung::test_unbekanntes_projekt_liefert_nichts` |
| T11 | Nur Dateien in einem Ordner mit gültiger Projekt-ID werden eingelesen. | `project_of()` prüft den ersten Ordner gegen `PROJECT_ID_PATTERN`; alles andere landet in `IngestResult.rejected` | `pipeline.ingest`, `pipeline.project_of` | `test_pipeline.py::TestProjektIdAmEingang::test_lose_datei_wird_abgewiesen_und_gemeldet`, `…::test_ordner_mit_ungueltigem_namen_wird_abgewiesen` |
| T12 | Jede Projekt-ID hat ein gültiges Format – am Eingang und im Modell. | `validate_project_id()` an jedem Eingang (`ingest`, `discover`, `index_chunks`, `fetch_known_chunk_ids`, `search`, `vector_search`, `text_search`); zusätzlich Typ `ProjectId` in `Document`, `Segment`, `Chunk` | `models.validate_project_id`, `models.ProjectId` | `test_models.py::TestProjektId` (14 Fälle, u. a. `".."`, `"lose_datei.pdf"`), `test_pipeline.py::…::test_pfadbestandteile_als_projekt_id_werden_abgelehnt`, `test_search.py::TestProjektIdInDerSuche` |
| T10 | Die Trennung hält auch mit echten Daten. | Kontrollprojekt BAU-43 mit gleichen Begriffen, gleichen Dateinamen und gegenteiligem Sachstand | `docs/testdaten.md` | `evaluate_search.py` meldet „Treffer aus fremdem Projekt": 0 bei 20 Fragen |

**Die Schlüsselprobe ist T7.** Die Tests legen in BAU-42 und BAU-43 Chunks mit **identischem Vektor** an. Selbst bei perfekter Ähnlichkeit erscheint der fremde Chunk nicht. Die Trennung beruht also auf dem Filter, nicht darauf, dass fremde Inhalte zufällig unähnlich sind.

### 2.3 Bekannte Grenzen (Stand heute)

Zwei der folgenden Punkte wurden beim Schreiben dieses Dokuments per Stichprobe gefunden und sind **nicht behoben**.

| # | Grenze | Nachweis | Folge | Vorschlag |
|---|---|---|---|---|
| G1 | ~~`project_id` wird nicht geprüft~~ **behoben**: Dateien ohne gültigen Projektordner werden abgewiesen und in `IngestResult.rejected` gemeldet | Stichprobe vorher: `data/raw/lose_datei.pdf` → `project_id = "lose_datei.pdf"`; nachher: abgewiesen | – | siehe T11 |
| G2 | ~~Filter in `ingest` über Pfadbestandteile umgehbar~~ **behoben**: Formatprüfung an jedem Eingang | Stichprobe vorher: `ingest(project_id="..")` verarbeitete alle Projekte; nachher: `ValueError` | – | siehe T12 |
| G3 | Optionale Projektfilter beim Einlesen und Einbetten | `ingest`, `index_chunks`, `fetch_known_chunk_ids`: `project_id=None` bedeutet „alle" | gewollt für Stapelverarbeitung, darf aber nie über eine Nutzerschnittstelle erreichbar sein | in einer API nur die Suchfunktionen freigeben |
| G4 | Logische statt physischer Trennung | eine Tabelle, drei Parquet-Dateien für alle Projekte | ein Fehler in einer *künftigen* Abfrage ohne `WHERE project_id` würde Projekte mischen | PostgreSQL Row-Level Security mit `current_setting('app.project_id')`; Parquet nach Projekt partitionieren |
| G5 | Keine Berechtigungen | Wer `search` aufruft, kann jede Projekt-ID übergeben | Die Produktvision verlangt „Projektgrenzen **und Berechtigungen**". Umgesetzt ist nur Ersteres. | in der `report-api` (Phase 3): Nutzer ↔ Projekt-Zuordnung prüfen, bevor `project_id` an `search` geht |
| G6 | Entwicklerwerkzeug ohne Trennung | `scripts/query_parquet.py` führt beliebiges SQL über alle Projekte aus | unkritisch lokal, darf aber nie Teil eines Dienstes werden | ausdrücklich als Entwicklerwerkzeug belassen |

**Einordnung:** Innerhalb der Suche, also dem Weg, auf dem Inhalte zu einem Nutzer oder später zum Sprachmodell gelangen, ist die Trennung durch Signaturen, SQL-Filter und Tests abgesichert (T6 bis T10). Die Lücken am **Eingang** (G1, G2) sind durch die Formatprüfung geschlossen (T11, T12). Offen bleiben die **fehlende Berechtigungsschicht** (G5, Phase 3) und die nur logische Trennung (G4).

### 2.4 Regeln für neuen Code

1. Jede Funktion, die Inhalte **liest und nach außen gibt**, nimmt `project_id: str` als Pflichtargument ohne Vorgabewert.
2. Jede SQL-Abfrage auf `chunks` außerhalb von Wartungsfunktionen enthält `WHERE project_id = %(project_id)s`, mit Parameterbindung und nie per String-Verkettung.
3. `project_id` wird nur in `pipeline.build_document` gesetzt und danach nur vererbt.
4. Jeder neue Eingang, an dem eine Projekt-ID ankommt, ruft `validate_project_id()` auf, bevor irgendetwas gelesen wird. Neue Modelle verwenden den Typ `ProjectId`, nicht `str`.
5. Jede neue Suchfunktion bekommt einen Test nach dem Muster `test_gleicher_vektor_anderes_projekt_bleibt_draussen`, also mit absichtlich identischem Inhalt im Fremdprojekt.
