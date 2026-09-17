# Produktvision: KI-gestützte Wissens- und Risikoanalyseplattform für Bauprojekte

Entwickle eine KI-gestützte Wissens- und Risikoanalyseplattform für Bauprojekte.

Die Plattform soll unterschiedliche Bauprojekt-Dokumente aufnehmen, deren Inhalte extrahieren, semantisch indizieren und für natürliche Sprachsuche sowie die Erstellung von Risikomanagement-Reports verwenden.

## Zu unterstützende Dokumentarten

- Baubesprechungs- und Gesprächsprotokolle
- Projektstatus- und Wochenberichte
- Terminpläne, Meilenstein- und Projektpläne
- Baugenehmigungen und Behördenkorrespondenz
- Auflagen, Nachweise und Prüfberichte
- Kostenberichte, Budgetübersichten und Nachtragslisten
- Abnahmeberichte
- Planungs- und technische Unterlagen
- Leistungsverzeichnisse und Ausschreibungsunterlagen
- Bauverträge, Vergabeunterlagen und Behinderungsanzeigen

## Beispielfragen

Die Plattform soll Fragen in natürlicher Sprache beantworten können, beispielsweise:

- Welche Risiken gefährden den Baubeginn?
- Welche Genehmigungen sind noch offen?
- Welche Meilensteine sind gefährdet?
- Welche Gewerke haben Termin- oder Kostenprobleme?
- Welche Aufgaben sind überfällig?
- Welche Nachträge oder Mängel sind noch ungeklärt?
- Welche Entscheidungen oder Planfreigaben fehlen?

Die Antworten müssen auf konkrete Dokumentstellen zurückverweisen können. Jede relevante Aussage soll Dokument, Version, Seite oder Abschnitt und einen Textauszug nennen.

## Risikokategorien

Die Lösung soll potenzielle Risiken erkennen und strukturieren, unter anderem nach:

- Terminrisiko
- Kostenrisiko
- Genehmigungsrisiko
- Planungsrisiko
- Qualitätsrisiko
- Vertragsrisiko
- Ressourcenrisiko
- Lieferantenrisiko
- Schnittstellenrisiko

Ein Risiko soll mindestens Titel, Kategorie, Beschreibung, betroffenen Projektbereich, mögliche Auswirkung, Wahrscheinlichkeit, Schweregrad, Verantwortlichen, empfohlene Maßnahme, Status und Quellenbelege enthalten.

## Pipeline-Schritte

1. Aufnahme der Originaldokumente
2. Extraktion von Text und Struktur
3. Normalisierung und Metadatenanreicherung
4. Aufteilung in semantische Textabschnitte
5. Speicherung analytischer Daten
6. Erzeugung von Embeddings
7. Indexierung in einer Vektordatenbank
8. Semantische Suche
9. KI-gestützte Analyse
10. Erstellung eines quellenbasierten Risiko- und Statusreports

## Wichtige Anforderungen

- Originaldokumente müssen erhalten bleiben.
- Dokumente müssen eindeutig Projekten zugeordnet sein.
- Projektgrenzen und Berechtigungen müssen eingehalten werden.
- Dokumentversionen müssen unterscheidbar sein.
- Aussagen müssen nachvollziehbar und quellenbasiert sein.
- Fakten, Schlussfolgerungen und Unsicherheiten müssen getrennt werden.
- Neue Dokumente sollen inkrementell verarbeitet werden können.
- Neue Dokumenttypen und Analysefunktionen sollen später ergänzt werden können.

## Erster Prototyp

Für den ersten Prototyp soll nur ein fiktives Bauprojekt mit PDF- und DOCX-Dokumenten unterstützt werden. Der Fokus liegt auf Gesprächsprotokollen, Statusberichten, Terminplänen und Genehmigungsunterlagen. Das erste Ziel ist eine semantische Suche mit Quellenangaben sowie ein erster strukturierter Risikobericht.
