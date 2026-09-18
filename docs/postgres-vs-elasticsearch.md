# PostgreSQL oder Elasticsearch als Suchkomponente

**Frage:** Soll die Suche (Phase 2) auf PostgreSQL mit pgvector bleiben, oder wäre Elasticsearch die bessere Grundlage?

**Rahmen:**
- Verglichen werden Suchfähigkeiten und Schnittstellen. Betrieb (Cluster, Speicher, Überwachung, Kosten des Betriebs) ist bewusst ausgeklammert.
- Die Angaben zu PostgreSQL sind in diesem Projekt gemessen oder im Code belegt.
- Die Angaben zu Elasticsearch stammen aus der offiziellen Dokumentation (Stand September 2026, Version 9.x). Die JSON-Beispiele sind **nicht ausgeführt**.
- Bezug zum Projekt: [spezifikation.md](spezifikation.md) (Schnittstellen, Projekttrennung), [diagrams/search.puml](diagrams/search.puml) (Ablauf der Hybrid-Suche).

---

## 1. Kurzfassung

| Kriterium | PostgreSQL + pgvector | Elasticsearch | Vorteil |
|---|---|---|---|
| Relevanz im Volltext | `ts_rank_cd`: zählt Vorkommen und Nähe, **ohne** Seltenheit im Bestand (kein IDF) | BM25 als Standard, seltene Begriffe wiegen mehr | **ES** |
| Deutsche Komposita | nicht eingebaut; Ispell-Wörterbücher oder Zerlegung außerhalb (hier: CharSplit in Python) | Token-Filter `hyphenation_decompounder` / `dictionary_decompounder`, brauchen Wortliste | **ES** (eingebaut, aber nicht ohne Pflege) |
| Tippfehler, unscharfe Suche | Erweiterung `pg_trgm` | `fuzziness` in der Abfrage | ES |
| Hervorhebung im Treffer | `ts_headline` | `highlight` mit mehreren Verfahren und Fragmenten | ES |
| Vektorsuche | `vector(n)`, exakt oder HNSW/IVFFlat | `dense_vector`, HNSW mit Quantisierung, exakt per `script_score` | gleichwertig |
| Filter bei Vektorsuche | bei Index: **nach** dem Durchsuchen, ab pgvector 0.8 iterativ nachgeladen | **während** der Suche, `k` Treffer garantiert | **ES** (sobald ein Index nötig ist) |
| Hybrid-Suche | selbst gebaut (SQL + Rangfusion in Python) | Retriever `rrf` / `linear` in **einer** Anfrage | **ES** (weniger eigener Code) |
| Datenhaltung | Suchindex = Datenbank, transaktional, Joins | zweiter Datenbestand neben der Quelle, nahezu Echtzeit | **Postgres** |
| Schema-Änderung | `ALTER TABLE`, berechnete Spalten | Analysator ändern = Index neu aufbauen | Postgres |
| Projekttrennung | `WHERE project_id`, zusätzlich Row-Level Security möglich | Filter je Retriever, gefilterte Aliasse, Index je Mandant, Sicherheit auf Dokumentebene | gleichwertig, unterschiedlich |
| Schnittstelle | SQL, eine Sprache für alles | REST/JSON (Query DSL), eigene Sprache | Geschmackssache; SQL für dieses Team |
| Lernwert für dieses Projekt | jeder Schritt sichtbar und selbst gebaut | vieles in einer Anfrage verborgen | Postgres |

**Ergebnis für dieses Projekt:** Postgres bleibt die richtige Wahl. Die Hybrid-Suche erreicht 96 % Recall@10 gegen die bekannte Wahrheit. Die Stärken von Elasticsearch (BM25, eingebaute Komposita-Zerlegung, Hervorhebung, Hybrid-Suche mit einer Anfrage) spielen erst bei deutlich mehr Dokumenten und Nutzern ihre Größe aus. Abschnitt 6 nennt die Schwellen.

---

## 2. Suchfähigkeiten im Einzelnen

### 2.1 Volltext: Relevanz

**PostgreSQL** bewertet mit `ts_rank` bzw. `ts_rank_cd`. Beide zählen, wie oft und wie nah beieinander die Suchbegriffe vorkommen. Sie berücksichtigen aber **nicht, wie selten ein Begriff im gesamten Bestand ist**.

In diesem Projekt ist das messbar. Bei „Welche Genehmigungen sind offen?" bekam „offen" dasselbe Gewicht wie „Genehmigung". „offen" steht aber als Statuswert in fast jeder Zeile des Bauzeitenplans. Das Ergebnis waren neun Treffer mit exakt gleichem Rang 0,100 – Rauschen, das die Rangfusion störte.

**Elasticsearch** bewertet standardmäßig mit **BM25**. Ein Begriff, der in vielen Dokumenten vorkommt, zählt wenig, ein seltener viel. „N-07" oder „BA-2026-0587" würden stark gewichtet, „offen" schwach. Genau das Rauschproblem oben würde BM25 weitgehend entschärfen.

Postgres kann gegensteuern: mit Gewichtsklassen (`setweight`, A–D, etwa Überschrift höher als Text) oder mit Erweiterungen, die BM25 nachrüsten. Das ist Zusatzaufwand, Elasticsearch bringt es mit.

### 2.2 Volltext: deutsche Sprache

| Aufgabe | PostgreSQL | Elasticsearch |
|---|---|---|
| Stammformen | Konfiguration `german` (Snowball) | Analysator `german` (Stemmer) |
| Stoppwörter | eingebaut | eingebaut |
| Umlaute vereinheitlichen | Erweiterung `unaccent` | Filter `german_normalization` |
| **Komposita zerlegen** | nur mit Ispell/Hunspell-Wörterbuch mit Komposita-Regeln, **nicht** in der Standardkonfiguration | Token-Filter `dictionary_decompounder` (Wortliste) oder `hyphenation_decompounder` (Silbentrennmuster + Wortliste, laut Dokumentation meist vorzuziehen) |

Beide Systeme **ergänzen** die Teile, statt das Wort zu ersetzen. Das ist dasselbe Prinzip wie unsere Spalte `compound_terms`.

Der Unterschied liegt im Verfahren:
- **Elasticsearch** zerlegt **wörterbuchbasiert**. Nur Teile, die in der Wortliste stehen, werden abgetrennt. „Sept + ember" kann so nicht entstehen. Dafür muss die Wortliste gepflegt werden, und ein Fachbegriff, der fehlt, wird nicht zerlegt.
- **Unser Weg (CharSplit)** zerlegt **statistisch**, ohne Wortliste. Das brauchte eine gemessene Schwelle (0,6), weil darunter Unsinn entsteht („Bear + beitung"). Die Messung steht in [../src/bauprojekt/compounds.py](../src/bauprojekt/compounds.py).

Für ein Bauvokabular wäre eine gepflegte Wortliste wahrscheinlich genauer. Den Aufwand dafür trägt man in beiden Systemen selbst: In Postgres steckt sie im Ispell-Wörterbuch, in Elasticsearch in der Wortliste.

### 2.3 Unscharfe Suche und Hervorhebung

- **Tippfehler:** Elasticsearch erlaubt `fuzziness` direkt in `match`. Postgres braucht `pg_trgm` (Trigramm-Ähnlichkeit) als zusätzliche Abfrage. Für Baudokumente, die aus Dateien stammen und nicht getippt werden, ist das nachrangig. Relevant wäre es für die Eingabe der Frage.
- **Hervorhebung:** Postgres liefert mit `ts_headline` einen Auszug mit markierten Treffern. Elasticsearch bietet mehrere Hervorhebungsverfahren, mehrere Fragmente je Treffer und die Wahl der Felder. Für die Quellenbelege in Phase 3 wäre das komfortabler. Unser Modell kommt aber schon ohne aus: `char_start`/`char_end` zeigen die genaue Stelle im Segment.

### 2.4 Vektorsuche

| | pgvector | Elasticsearch |
|---|---|---|
| Feldtyp | `vector(768)`, dazu `halfvec`, `sparsevec`, `bit` | `dense_vector` (`dims`, `similarity`, `element_type`) |
| Ähnlichkeit | Operatoren `<=>` Cosinus-Abstand, `<->` L2, `<#>` Skalarprodukt | `similarity: cosine \| dot_product \| l2_norm \| max_inner_product` |
| Exakte Suche | Standard ohne Index (**so läuft es hier**) | `script_score` mit `cosineSimilarity(...)` |
| Näherungssuche | Index HNSW oder IVFFlat | HNSW (Standard) oder DiskBBQ, mit Quantisierung |
| Indizierbare Dimensionen | `vector` bis 2.000, `halfvec` bis 4.000 | für 768 Dimensionen ohne Einschränkung |

Bei 768 Dimensionen und einigen tausend Chunks sind beide gleichwertig. Unterschiede zeigen sich erst mit Index. Dann zählt vor allem 2.5.

### 2.5 Filter bei der Vektorsuche – wichtig für die Projekttrennung

Das ist der fachlich interessanteste Unterschied, weil er direkt `WHERE project_id = …` betrifft.

- **pgvector mit Index:** Laut Dokumentation wird der Filter **nach** dem Durchsuchen des Index angewendet. Der HNSW-Index liefert die nächsten Nachbarn **über alle Projekte**, erst danach werden fremde entfernt. Bei einem kleinen Projekt unter vielen großen bleiben so womöglich nur zwei von zehn gewünschten Treffern übrig. Das Ergebnis ist **unvollständig, aber nicht falsch**: Es erscheint nie ein fremder Treffer. Ab pgvector 0.8 lässt sich das mit „iterativen Index-Scans" beheben (`hnsw.iterative_scan`), die so lange nachladen, bis genug Treffer da sind.
- **Elasticsearch:** Der Filter im `knn` wird laut Dokumentation **während** der Näherungssuche angewendet, und es werden `k` passende Treffer garantiert.

**Heute betrifft uns das nicht**, weil wir ohne Index exakt suchen. Sobald ein HNSW-Index nötig wird, ist es der Punkt, den man bei pgvector aktiv einstellen muss und bei Elasticsearch geschenkt bekommt.

### 2.6 Hybrid-Suche

**PostgreSQL / dieses Projekt:** zwei SQL-Abfragen und eine Rangfusion in Python (`search.reciprocal_rank_fusion`, rund 10 Zeilen). Die Dokumentation von pgvector sagt ausdrücklich, dass Hybrid-Suche nicht eingebaut ist, und empfiehlt Reciprocal Rank Fusion. Der Vorteil: Jeder Schritt ist sichtbar, messbar (`evaluate_search.py` misst beide Verfahren getrennt) und änderbar.

**Elasticsearch:** Retriever kombinieren Verfahren in einer Anfrage:
- `rrf` für Reciprocal Rank Fusion,
- `linear` für gewichtete Summen,
- `text_similarity_reranker` für einen nachgeschalteten Reranker, also Vorschlag 4 aus unserer Liste.

Dasselbe Ergebnis, weniger eigener Code, aber auch weniger Einblick. Siehe Beispiel in 3.3.

### 2.7 Auswertungen und Facetten

Elasticsearch liefert Aggregationen (etwa Treffer je Dokumentart oder Monat) in derselben Anfrage wie die Suche. Postgres erledigt das mit `GROUP BY`, in einer zweiten Abfrage oder als Teil der ersten. Für einen Risikobericht, der ohnehin gezielt nach Kategorien sucht, ist das kein entscheidender Unterschied.

---

## 3. Schnittstellen

### 3.1 PostgreSQL: SQL

- **Protokoll:** PostgreSQL-Protokoll; in Python `psycopg`, Vektortypen über `pgvector.psycopg.register_vector`.
- **Sprache:** SQL. Schema (DDL), Schreiben und Suchen in einer Sprache.
- **Schema:** Tabelle mit festen Typen. Die Volltextspalte ist eine **berechnete Spalte**, die Postgres beim Schreiben selbst pflegt:
  ```sql
  text_search tsvector GENERATED ALWAYS AS (
      to_tsvector('german', coalesce(heading, '') || ' ' || text || ' ' || compound_terms)
  ) STORED
  ```
- **Schreiben:** `INSERT … ON CONFLICT (chunk_id) DO UPDATE`, transaktional. Nach dem `COMMIT` sofort sichtbar.
- **Parameter:** Bindung über `%(project_id)s`, Werte werden nie in den SQL-Text eingefügt.
- **Joins:** möglich. Wir brauchen sie für die Suche nicht, weil die Herkunft im Chunk steht.

### 3.2 Elasticsearch: REST und Query DSL

- **Protokoll:** HTTP/JSON (REST). In Python das Paket `elasticsearch` (`es.search(...)`, `helpers.bulk(...)`). Daneben gibt es die Abfragesprache ES|QL.
- **Sprache:** Query DSL, verschachteltes JSON. Mapping, Analysatoren und Abfragen sind je eigene JSON-Strukturen.
- **Schema (Mapping):** Feldtypen und Analysatoren werden beim Anlegen des Index festgelegt. **Ein geänderter Analysator greift nicht rückwirkend.** Der Index muss neu aufgebaut werden (Reindex). Das entspricht unserem `embed_chunks.py --neu`, betrifft aber auch Änderungen am Volltext, nicht nur an Vektoren.
- **Schreiben:** einzeln oder per Bulk-API. Sichtbar nach dem nächsten Refresh (Standard: etwa 1 Sekunde), also nahezu Echtzeit. Es gibt keine Transaktion über mehrere Dokumente.
- **Datenfluss:** Elasticsearch wäre ein **zweiter Datenbestand** neben der Quelle (Parquet, später Postgres). Jede Änderung muss in beide gelangen. Genau an solchen Übergängen entstehen Abweichungen: ein Dokument, das im Index fehlt oder dort noch in alter Version steht.

### 3.3 Dieselbe Suche in beiden Schnittstellen

**PostgreSQL, wie in `search.py` (vereinfacht):**

```sql
-- 1. Vektorsuche
SELECT chunk_id, 1 - (embedding <=> %(q)s::vector) AS similarity
FROM chunks
WHERE project_id = %(project_id)s
ORDER BY embedding <=> %(q)s::vector
LIMIT 30;

-- 2. Volltextsuche (Wörter mit ODER verknüpft)
SELECT chunk_id, ts_rank_cd(text_search, q) AS rank
FROM chunks, to_tsquery('german', 'genehm | off') AS q
WHERE project_id = %(project_id)s AND text_search @@ q
ORDER BY rank DESC
LIMIT 30;

-- 3. Rangfusion in Python: Punkte = Summe 1 / (60 + Rang)
```

**Elasticsearch, gleichwertig (nicht ausgeführt, nach Dokumentation):**

```json
POST /chunks/_search
{
  "retriever": {
    "rrf": {
      "retrievers": [
        {
          "standard": {
            "query":  { "match": { "text": "Welche Genehmigungen sind offen?" } },
            "filter": { "term":  { "project_id": "BAU-42" } }
          }
        },
        {
          "knn": {
            "field": "embedding",
            "query_vector": [0.012, -0.034, "…768 Werte…"],
            "k": 30,
            "num_candidates": 100,
            "filter": { "term": { "project_id": "BAU-42" } }
          }
        }
      ]
    }
  },
  "highlight": { "fields": { "text": {} } }
}
```

Dazu ein Mapping mit deutschem Analysator und Komposita-Filter:

```json
PUT /chunks
{
  "settings": {
    "analysis": {
      "filter": {
        "deutsch_stamm": { "type": "stemmer", "language": "light_german" },
        "bau_komposita": {
          "type": "hyphenation_decompounder",
          "hyphenation_patterns_path": "analysis/de_DR.xml",
          "word_list_path": "analysis/bauwoerter.txt"
        }
      },
      "analyzer": {
        "deutsch_bau": {
          "tokenizer": "standard",
          "filter": ["lowercase", "bau_komposita", "german_normalization", "deutsch_stamm"]
        }
      }
    }
  },
  "mappings": {
    "properties": {
      "project_id": { "type": "keyword" },
      "text":       { "type": "text", "analyzer": "deutsch_bau" },
      "heading":    { "type": "text", "analyzer": "deutsch_bau" },
      "embedding":  { "type": "dense_vector", "dims": 768, "similarity": "cosine" }
    }
  }
}
```

**Beobachtung:** Der Filter `project_id` steht in Elasticsearch **zweimal**, in jedem Retriever. Laut Dokumentation gilt ein Filter nur im jeweiligen Retriever, nicht für die Kombination. Wer ihn in einem vergisst, bekommt über diesen Zweig fremde Treffer. Das ist dieselbe Fehlerklasse wie ein vergessenes `WHERE` in Postgres. Deshalb gilt auch dort die Regel aus [spezifikation.md](spezifikation.md) § 2.4: Die Projekt-ID gehört als Pflichtargument in eine einzige Funktion, die beide Zweige baut.

---

## 4. Projekttrennung (Mandanten) im Vergleich

| Mittel | PostgreSQL | Elasticsearch |
|---|---|---|
| Filter je Abfrage | `WHERE project_id = …` (**heute umgesetzt**, T7 in der Spezifikation) | `filter: term project_id` je Retriever |
| Erzwungen durch das System | **Row-Level Security**: Postgres hängt die Bedingung selbst an jede Abfrage | **Sicherheit auf Dokumentebene** (Rollen mit Dokumentfilter); laut Elastic-Preisseite in der Enterprise-Stufe |
| Sicht je Projekt | Sicht (`VIEW`) oder Schema je Projekt | **gefilterter Alias** je Projekt: der Alias trägt den Filter, der Aufrufer sieht nur „seinen" Index |
| Physische Trennung | Tabelle, Schema oder Datenbank je Projekt | Index je Projekt |

Beide Systeme können die Trennung **vom Aufrufer weg ins System verlagern**. Das wäre die Antwort auf Grenze G4 in der Spezifikation. In Postgres geschieht das über Row-Level Security, in Elasticsearch über gefilterte Aliasse oder Sicherheit auf Dokumentebene. Postgres hat hier den Vorteil, dass Row-Level Security ohne Zusatzlizenz Teil der Datenbank ist.

---

## 5. Lizenz (nur zur Einordnung)

- **PostgreSQL** und **pgvector** stehen unter freien Lizenzen ohne Funktionsstufen.
- **Elasticsearch** ist quelloffen verfügbar (u. a. AGPL, Elastic License). Einzelne Funktionen sind laut der Elastic-Preisseite für selbst betriebene Installationen an kostenpflichtige Stufen gebunden, darunter die Retriever-Kombinationen (RRF, linear) und die Sicherheit auf Dokument- und Feldebene. Die Zuordnung ändert sich zwischen Versionen und sollte vor einer Entscheidung am konkreten Stand geprüft werden.
- **OpenSearch** (Apache 2.0, aus Elasticsearch hervorgegangen) bietet vergleichbare Schnittstellen und wäre bei einem Wechsel die naheliegende Alternative.

---

## 6. Bewertung für dieses Projekt

**Heute: bei PostgreSQL bleiben.** Die Gründe:

1. **Die Qualität ist gemessen gut:** 96 % Recall@10 über 20 Testfragen. Die Schwachstellen (Komposita, Rauschen durch häufige Wörter) sind erkannt; die eine ist behoben, die andere eingegrenzt.
2. **Eine Quelle, keine Synchronisation:** Suchindex und Datenbank sind dasselbe System. Ein zweiter Datenbestand wäre eine neue Fehlerquelle, gerade für die Projekttrennung.
3. **Lernwert:** Rangfusion, Präfixe, Komposita-Zerlegung, Filterlogik liegen offen im Code. Genau diese Einsichten hätte eine einzelne Elasticsearch-Anfrage verborgen.

**Wann Elasticsearch (oder OpenSearch) ernsthaft zu prüfen ist:**

| Anlass | Warum |
|---|---|
| Deutlich mehr Dokumente, Vektorindex nötig, viele kleine Projekte | Filter während der Näherungssuche (2.5) statt nachträglich |
| Relevanz im Volltext wird zum Engpass, etwa Rauschen durch häufige Statuswörter | BM25 mit Seltenheitsgewichtung (2.1) |
| Nutzer tippen Fragen frei ein, mit Tippfehlern | `fuzziness` (2.3) |
| Oberfläche mit Facetten und Trefferhervorhebung | Aggregationen und `highlight` in einer Anfrage (2.3, 2.7) |
| Reranking wird eingeführt | Retriever `text_similarity_reranker` in derselben Anfrage (2.6) |

**Vorher lohnt sich in Postgres:**
- Gewichtsklassen mit `setweight` (Überschrift höher als Text) gegen das Rauschen aus 2.1.
- Row-Level Security gegen Grenze G4.

Beide Änderungen sind klein und lassen sich mit `evaluate_search.py` messen, bevor über einen Systemwechsel entschieden wird.

Falls es dazu kommt, erleichtert die bestehende Schnittstelle den Wechsel: `search(connection, *, project_id, question, encoder, …) -> list[SearchHit]`. Eine zweite Umsetzung mit Elasticsearch ließe sich hinter derselben Signatur bauen und mit denselben 20 Fragen gegen die erste messen.
