# Synthetische Testdaten

Erzeugt mit `uv run python scripts/generate_sample_documents.py` nach `data/raw/`. Die Ausgabe ist reproduzierbar: Gleicher Inhalt ergibt denselben SHA-256. Wer die Dokumente neu erzeugt, legt also keine neuen Versionen an.

Diese Datei ist die **bekannte Wahrheit**, gegen die Extraktion, Suche und Risikoanalyse geprüft werden. Wer Inhalte im Skript ändert, muss diese Datei anpassen.

## BAU-42 – Wohnquartier Lindenhof, Haus A und B

| Datei | Typ | Seiten / Einheit |
|---|---|---|
| `protokolle/2026-09-01_baubesprechung.docx` | Protokoll Nr. 23 | TOP-Tabelle (TOP 1–5) |
| `protokolle/2026-09-08_baubesprechung.docx` | Protokoll Nr. 24 | TOP-Tabelle (TOP 1–5) |
| `protokolle/2026-09-15_baubesprechung.docx` | Protokoll Nr. 25 | TOP-Tabelle (TOP 1–5) |
| `statusberichte/statusbericht_2026-08.pdf` | Statusbericht, Stand 31.08. | 3 Seiten |
| `statusberichte/statusbericht_2026-09.pdf` | Statusbericht, Stand 15.09. | 4 Seiten |
| `terminplan/bauzeitenplan.xlsx` | Bauzeitenplan | Blatt „Bauzeitenplan“, V01–V09 |
| `genehmigungen/baugenehmigung.pdf` | Teilbaugenehmigung Haus A | 2 Seiten |
| `genehmigungen/behördenkorrespondenz.pdf` | 3 Schreiben | 1 Schreiben pro Seite |

### Bewusst eingebaute Sachverhalte

| # | Sachverhalt | Belege |
|---|---|---|
| S1 | **Baugenehmigung Haus B nicht erteilt**, der Antrag ruht (Haus A hat nur eine Teilbaugenehmigung) | Protokoll 24 TOP 4 · Statusbericht 09 S. 1–2 · Korrespondenz S. 1, S. 3 · Baugenehmigung S. 1 · Bauzeitenplan V07 |
| S2 | **Fassadenplanung verspätet**: 05.09. verpasst, neuer Termin 19.09. unsicher | Protokoll 23 TOP 3 (Zusage) · Protokoll 24 TOP 3 · Protokoll 25 TOP 2 · Statusbericht 09 S. 2 · V03 |
| S3 | **Rohbau Haus A zwei Wochen im Verzug**: Fertigstellung 13.11. statt 30.10. | Protokoll 23 TOP 1 (1 Woche) · Protokoll 24 TOP 1 · Protokoll 25 TOP 1 · Statusbericht 08 S. 1 (5 AT) · Statusbericht 09 S. 2 · V02 |
| S4 | **Nachtrag N-07 Fassade offen**: 48.500 EUR, ungeprüft | Protokoll 25 TOP 2 · Statusbericht 09 S. 3–4 |
| S5 | **Kein Verantwortlicher für die Brandschutzprüfung**: Bauherr und Architekt schieben die Zuständigkeit hin und her | Protokoll 23 TOP 2 · Protokoll 24 TOP 2 · Protokoll 25 TOP 3 · Statusbericht 09 S. 1, S. 4 · V06 („nicht benannt“) |
| S6 | **Baubeginn Haus B (12.10.) gefährdet** | Protokoll 25 TOP 4 · Statusbericht 09 S. 1–2 · V08 |

### Zusammenhänge, die erst beim Kombinieren sichtbar werden

- **Ursachenkette:** Niemand ist verantwortlich (S5), daher fehlt der Prüfbericht Brandschutz, daher ruht die Genehmigung (S1), daher ist der Baubeginn gefährdet (S6).
- **Eine Folgerung, die in keinem Dokument steht:** Die Behörde setzt eine Frist bis 30.09. und braucht danach etwa 4 Wochen (Korrespondenz S. 3). Eine Genehmigung vor Ende Oktober ist damit kaum möglich, der 12.10. lässt sich also nicht halten.
- **Weitere Ursachenkette:** Die Brandschutzauflage für nichtbrennbare Dämmung (Baugenehmigung S. 2, A3) erzwingt eine Planänderung. Daraus folgen die verspätete Fassadenplanung (S2) und der Nachtrag N-07 (S4). Wenn die Pläne nicht bis 26.09. bei Metallbau Hofer sind, verzögert sich die Fertigung (V04, V05).
- **Entwicklung über die Zeit:** Der Verzug im Rohbau steigt von 5 Arbeitstagen (Statusbericht 08) über 1 Woche (Protokoll 23) auf 2 Wochen (Protokoll 24). Der Gesamtstatus wechselt von GELB auf ROT. Ältere Aussagen sind damit überholt.
- **Einschätzung statt Fakt:** „Verschiebung um 4 bis 6 Wochen“ ist ausdrücklich als nicht bestätigte Einschätzung markiert (Protokoll 25 TOP 4).

### Ablenker: erledigte Punkte, die nicht als Risiko erscheinen dürfen

Sondernutzungserlaubnis Kran (Protokoll 23 TOP 4) · N-05 beauftragt (Protokoll 23 TOP 5) · SiGeKo ohne Beanstandung (Protokoll 24 TOP 5) · Kanalanschluss genehmigt (Protokoll 25 TOP 5) · Standsicherheitsnachweis geprüft (Baugenehmigung S. 2, A4)

## BAU-43 – Erweiterung Grundschule am Park (Kontrollprojekt)

Dieses Projekt prüft, ob die Projekte sauber getrennt bleiben. Es verwendet **dieselben Begriffe mit gegenteiligem Stand** und teilweise **dieselben Dateinamen** wie BAU-42 (`statusberichte/statusbericht_2026-09.pdf`, `genehmigungen/baugenehmigung.pdf`).

| Datei | Inhalt |
|---|---|
| `protokolle/2026-09-10_baubesprechung.docx` | Rohbau im Plan · Fassadenplanung freigegeben · Prüfbericht Brandschutz liegt vor (Dr. Keller) · **Aufzug 6 Wochen Lieferverzug**, Nachtrag N-02 (3.800 EUR) offen |
| `statusberichte/statusbericht_2026-09.pdf` | 2 Seiten, Status GELB, Baugenehmigung erteilt, Kosten im Budget |
| `genehmigungen/baugenehmigung.pdf` | 1 Seite, Baugenehmigung **vollständig erteilt** am 02.03.2026 |

**Zeichen für vermischte Projekte:** Eine Suche in BAU-42 liefert „Baugenehmigung vollständig erteilt“, „Prüfbericht Brandschutz liegt vor“, „Aufzug“ oder „N-02“. Oder eine Suche in BAU-43 liefert Treffer zu Haus B, N-07 oder Lindenhof.
