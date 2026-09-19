"""Risikobericht als Markdown – reine Darstellung, keine Logik.

Aufbau: Kopf mit Laufdaten, Übersichtstabelle, je Risiko die Pflichtfelder, getrennt nach
Fakten (mit Quellennummer), Schlussfolgerungen und Unsicherheiten, am Ende das
Quellenverzeichnis mit Datei, Version, Stelle, Datum und den zitierten Auszügen.

Sortiert wird hier deterministisch nach Schweregrad, dann Wahrscheinlichkeit – die
Reihenfolge soll nicht davon abhängen, wie das Modell die Liste zufällig angeordnet hat.
"""

from bauprojekt.models import Chunk
from bauprojekt.risks import Level, Risk, RiskReport

LEVEL_RANK = {Level.HOCH: 0, Level.MITTEL: 1, Level.NIEDRIG: 2}


def ordered(risks: list[Risk]) -> list[Risk]:
    return sorted(
        risks, key=lambda r: (LEVEL_RANK[r.severity], LEVEL_RANK[r.probability])
    )


def render_markdown(report: RiskReport) -> str:
    risks = ordered(report.risks)
    numbers = source_numbers(risks)
    stats = report.stats
    lines = [
        f"# Risikobericht {report.project_id}",
        "",
        (
            f"Erstellt {report.created_at:%d.%m.%Y %H:%M} UTC mit `{report.model_name or '–'}` · "
            f"{stats.provided_chunks} Textstellen ausgewertet, {len(report.sources)} zitiert · "
            f"{stats.retries} Nachbesserungen · {thousands(stats.input_tokens)} / "
            f"{thousands(stats.output_tokens)} Tokens · {stats.seconds:.0f} s"
        ),
        "",
        "> Fakten sind wörtlich belegt und maschinell geprüft. Schlussfolgerungen und",
        "> Unsicherheiten stammen vom Sprachmodell und sind als solche gekennzeichnet.",
        "",
    ]
    if not risks:
        lines.append("Keine Risiken gefunden.")
        return "\n".join(lines) + "\n"

    lines += [
        "## Übersicht",
        "",
        "| # | Risiko | Kategorie | Schwere | Wahrsch. | Status | Verantwortlich |",
        "|---|---|---|---|---|---|---|",
    ]
    for number, risk in enumerate(risks, start=1):
        lines.append(
            f"| {number} | {cell(risk.title)} | {risk.category} | {risk.severity} | "
            f"{risk.probability} | {risk.status} | {cell(risk.owner)} |"
        )
    lines.append("")

    for number, risk in enumerate(risks, start=1):
        lines += render_risk(number, risk, numbers)

    lines += ["## Quellen", ""]
    for chunk_id, number in numbers.items():
        chunk = report.sources[chunk_id]
        lines.append(f"**[{number}]** {source_line(chunk)}")
        for excerpt in excerpts_of(chunk_id, risks):
            lines.append(f"> „{excerpt}“")
        lines.append("")
    return "\n".join(lines)


def render_risk(number: int, risk: Risk, numbers: dict[str, int]) -> list[str]:
    lines = [
        f"## {number}. {risk.title}",
        "",
        (
            f"**Kategorie** {risk.category} · **Bereich** {risk.project_area} · "
            f"**Schwere** {risk.severity} · **Wahrscheinlichkeit** {risk.probability} · "
            f"**Status** {risk.status} · **Verantwortlich** {risk.owner}"
        ),
        "",
        risk.description,
        "",
        f"**Auswirkung:** {risk.impact}",
        "",
        f"**Maßnahme:** {risk.measure}",
        "",
        "**Fakten**",
        "",
    ]
    for fact in risk.facts:
        refs = "".join(f"[{numbers[e.chunk_id]}]" for e in fact.evidence)
        lines.append(f"- {fact.statement} {refs}")
    lines.append("")
    if risk.conclusions:
        lines += ["**Schlussfolgerungen** (abgeleitet)", ""]
        lines += [f"- {text}" for text in risk.conclusions]
        lines.append("")
    if risk.uncertainties:
        lines += ["**Unsicherheiten**", ""]
        lines += [f"- {text}" for text in risk.uncertainties]
        lines.append("")
    return lines


def source_numbers(risks: list[Risk]) -> dict[str, int]:
    """Quellen in der Reihenfolge ihrer ersten Nennung durchnummerieren."""
    numbers: dict[str, int] = {}
    for risk in risks:
        for fact in risk.facts:
            for evidence in fact.evidence:
                numbers.setdefault(evidence.chunk_id, len(numbers) + 1)
    return numbers


def excerpts_of(chunk_id: str, risks: list[Risk]) -> list[str]:
    found: dict[str, None] = {}
    for risk in risks:
        for fact in risk.facts:
            for evidence in fact.evidence:
                if evidence.chunk_id == chunk_id:
                    found.setdefault(" ".join(evidence.excerpt.split()))
    return list(found)


def source_line(chunk: Chunk) -> str:
    """Quellenangabe mit Version: Die document_id ist aus dem Inhalts-Hash abgeleitet."""
    return f"{chunk.citation()} · Version {chunk.document_id[:8]}"


def thousands(number: int) -> str:
    """12345 → '12.345' (deutsches Tausendertrennzeichen)."""
    return f"{number:,}".replace(",", ".")


def cell(text: str) -> str:
    return text.replace("|", "\\|")
