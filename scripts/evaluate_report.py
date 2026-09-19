"""CLI: Risikoberichte gegen die bekannte Wahrheit bewerten (Regeln in scripts/report_cases.py).

Bewertet werden gespeicherte Berichte (``…json`` aus create_report.py), nicht neue Läufe.
Das Modell wird also nicht erneut aufgerufen, und mehrere Berichte lassen sich
nebeneinanderstellen – etwa ein lokales Modell gegen Claude.

Geprüft wird:

* **Sachverhalte S1–S6:** Nennt ein Risiko den Sachverhalt und zitiert es eine der
  erwarteten Fundstellen? Dazu der Anteil der erwarteten Fundstellen, die zitiert werden.
* **Zusammenhänge:** Stellt ein Risiko die Ursachenketten und Folgerungen her, die in
  keinem einzelnen Dokument stehen? Ist die Schätzung „4 bis 6 Wochen“ als Unsicherheit
  markiert?
* **Ablenker:** Erscheinen erledigte Punkte fälschlich als Risiko?
* **Projekttrennung:** Stammt jede Quelle aus dem Projekt, tauchen Begriffe aus BAU-43 auf?
* **Kennzahlen:** Umfang, Nachbesserungen, Tokens, Laufzeit.

Die Wortwahl des Modells wird nur mit Begriffen verglichen. Der Maßstab ist also grob:
Bei „nicht gefunden“ mit ``--details`` von Hand nachsehen.

Aufruf:
    uv run python scripts/evaluate_report.py data/generated/BAU-42/*.json
    uv run python scripts/evaluate_report.py bericht_a.json bericht_b.json --details
"""

import argparse
import re
from pathlib import Path

from report_cases import DISTRACTORS, FINDINGS, FOREIGN_TERMS, LINKS, Terms

from bauprojekt.risks import Risk, RiskReport

SHORT_EXCERPT = 20
"""Auszüge unter dieser Länge (Zeichen) belegen kaum etwas, bestehen aber die Quellenprüfung."""

LABEL_WIDTH = 46
COLUMN_WIDTH = 22


def normalize(text: str) -> str:
    return " ".join(text.lower().replace("–", "-").split())


def contains(text: str, term: str) -> bool:
    pattern = re.escape(term)
    if term[0].isdigit():
        pattern = r"(?<!\d)" + pattern
    return re.search(pattern, text) is not None


def matches(text: str, terms: Terms) -> bool:
    normalized = normalize(text)
    return all(any(contains(normalized, term) for term in group) for group in terms)


def own_words(risk: Risk) -> str:
    """Was das Modell selbst formuliert hat – ohne die wörtlichen Auszüge.

    Die Auszüge bleiben außen vor: Sonst gälte ein Zusammenhang schon als erkannt, weil
    ein zitierter Satz zufällig beide Begriffe enthält.
    """
    parts = [
        risk.title,
        risk.description,
        risk.project_area,
        risk.impact,
        risk.measure,
        risk.owner,
        *(fact.statement for fact in risk.facts),
        *risk.conclusions,
        *risk.uncertainties,
    ]
    return "\n".join(parts)


def headline(risk: Risk) -> str:
    return f"{risk.title}\n{risk.description}\n{risk.project_area}"


def cited_locations(risk: Risk, report: RiskReport) -> set[tuple[str, str]]:
    return {
        (report.sources[e.chunk_id].file_name, report.sources[e.chunk_id].locator)
        for fact in risk.facts
        for e in fact.evidence
    }


class Evaluation:
    """Alle Prüfungen für einen Bericht, als Zeilen für die Vergleichstabelle."""

    def __init__(self, report: RiskReport) -> None:
        self.report = report
        self.rows: dict[str, str] = {}
        self.notes: dict[str, list[str]] = {}
        self.findings()
        self.links()
        self.distractors()
        self.isolation()
        self.figures()

    def findings(self) -> None:
        found = 0
        for finding in FINDINGS:
            risks = [
                r
                for r in self.report.risks
                if matches(own_words(r), finding.terms)
                and cited_locations(r, self.report) & finding.locations
            ]
            cited = set().union(*(cited_locations(r, self.report) for r in risks))
            covered = len(cited & finding.locations)
            if risks:
                found += 1
                self.rows[f"  {finding.label}"] = (
                    f"✓ {covered}/{len(finding.locations)} Stellen"
                )
                self.notes[finding.label] = [r.title for r in risks]
            else:
                self.rows[f"  {finding.label}"] = "✗"
        self.rows["Sachverhalte gefunden"] = f"{found}/{len(FINDINGS)}"

    def links(self) -> None:
        found = 0
        for link in LINKS:
            texts = [
                "\n".join(r.uncertainties) if link.only_uncertainties else own_words(r)
                for r in self.report.risks
            ]
            ok = any(matches(text, link.terms) for text in texts)
            found += ok
            self.rows[f"  {link.label}"] = "✓" if ok else "✗"
        self.rows["Zusammenhänge erkannt"] = f"{found}/{len(LINKS)}"

    def distractors(self) -> None:
        hits = [
            d.label
            for d in DISTRACTORS
            if any(matches(headline(r), d.terms) for r in self.report.risks)
        ]
        self.rows["Ablenker als Risiko (soll 0)"] = (
            f"{len(hits)} ✗ " + ", ".join(hits) if hits else "0 ✓"
        )

    def isolation(self) -> None:
        foreign_sources = sum(
            chunk.project_id != self.report.project_id
            for chunk in self.report.sources.values()
        )
        all_text = normalize(
            "\n".join(own_words(r) for r in self.report.risks)
            + "\n".join(c.text for c in self.report.sources.values())
        )
        foreign_terms = [t for t in FOREIGN_TERMS if t in all_text]
        self.rows["Quellen aus fremdem Projekt (soll 0)"] = (
            f"{foreign_sources} ✗" if foreign_sources else "0 ✓"
        )
        self.rows["Begriffe aus BAU-43 (soll 0)"] = (
            f"{len(foreign_terms)} ✗ " + ", ".join(foreign_terms)
            if foreign_terms
            else "0 ✓"
        )

    def figures(self) -> None:
        risks = self.report.risks
        facts = [f for r in risks for f in r.facts]
        evidence = [e for f in facts for e in f.evidence]
        stats = self.report.stats
        self.rows["Risiken"] = str(len(risks))
        self.rows["Fakten / Belege"] = f"{len(facts)} / {len(evidence)}"
        self.rows["Quellen geliefert / zitiert"] = (
            f"{stats.provided_chunks} / {len(self.report.sources)}"
        )
        self.rows[f"Kurze Auszüge (< {SHORT_EXCERPT} Zeichen)"] = str(
            sum(len(e.excerpt.strip()) < SHORT_EXCERPT for e in evidence)
        )
        self.rows["Risiken ohne Schlussfolgerung"] = str(
            sum(not r.conclusions for r in risks)
        )
        self.rows["Nachbesserungen"] = str(stats.retries)
        self.rows["Tokens ein / aus"] = f"{stats.input_tokens} / {stats.output_tokens}"
        self.rows["Laufzeit"] = f"{stats.seconds:.0f} s"


ORDER = [
    "Sachverhalte gefunden",
    *(f"  {f.label}" for f in FINDINGS),
    "Zusammenhänge erkannt",
    *(f"  {link.label}" for link in LINKS),
    "Ablenker als Risiko (soll 0)",
    "Quellen aus fremdem Projekt (soll 0)",
    "Begriffe aus BAU-43 (soll 0)",
    "Risiken",
    "Fakten / Belege",
    "Quellen geliefert / zitiert",
    f"Kurze Auszüge (< {SHORT_EXCERPT} Zeichen)",
    "Risiken ohne Schlussfolgerung",
    "Nachbesserungen",
    "Tokens ein / aus",
    "Laufzeit",
]
SECTION_BREAKS = {"Zusammenhänge erkannt", "Ablenker als Risiko (soll 0)", "Risiken"}


def column_title(report: RiskReport) -> str:
    name = report.model_name.split("/")[-1] or "–"
    return f"{name[:14]} {report.created_at:%H:%M}"


def print_table(evaluations: list[Evaluation]) -> None:
    header = f"{'':<{LABEL_WIDTH}}" + "".join(
        f"{column_title(e.report):<{COLUMN_WIDTH}}" for e in evaluations
    )
    print(header)
    print("-" * len(header))
    for label in ORDER:
        if label in SECTION_BREAKS:
            print()
        cells = "".join(f"{e.rows.get(label, ''):<{COLUMN_WIDTH}}" for e in evaluations)
        print(f"{label:<{LABEL_WIDTH}}{cells}")


def print_details(path: Path, evaluation: Evaluation) -> None:
    report = evaluation.report
    print(f"\n=== {path.name} ({report.model_name})")
    for risk in report.risks:
        labels = [
            f.label.split()[0]
            for f in FINDINGS
            if risk.title in evaluation.notes.get(f.label, [])
        ]
        tag = f"  → {', '.join(labels)}" if labels else ""
        print(f"- [{risk.category}/{risk.severity}] {risk.title}{tag}")
    missing = [f.label for f in FINDINGS if f.label not in evaluation.notes]
    if missing:
        print(f"  nicht gefunden: {', '.join(missing)}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("reports", nargs="+", type=Path, help="Berichte als JSON")
    parser.add_argument(
        "--details", action="store_true", help="Risiken je Bericht mit Zuordnung zeigen"
    )
    args = parser.parse_args()

    evaluations = [
        Evaluation(RiskReport.model_validate_json(path.read_text(encoding="utf-8")))
        for path in args.reports
    ]
    for path, evaluation in zip(args.reports, evaluations, strict=True):
        if evaluation.report.project_id != "BAU-42":
            parser.error(f"{path}: Die Regeln gelten nur für BAU-42.")
    print_table(evaluations)
    if args.details:
        for path, evaluation in zip(args.reports, evaluations, strict=True):
            print_details(path, evaluation)


if __name__ == "__main__":
    main()
