"""Erwartungen an den Risikobericht für BAU-42 – die bekannte Wahrheit für evaluate_report.py.

Übersetzt docs/testdaten.md in prüfbare Regeln. Geprüft wird mit Begriffen und
Fundstellen, nicht mit einem zweiten Sprachmodell: Das ist grob, aber nachvollziehbar,
kostenlos und bei jedem Lauf gleich. Die Grenzen:

* Ein Sachverhalt mit ungewöhnlicher Wortwahl kann als „nicht gefunden“ gelten, obwohl er
  im Bericht steht. ``--details`` zeigt deshalb die Titel, um das von Hand nachzusehen.
* Ob eine Schlussfolgerung *richtig* begründet ist, prüfen die Begriffe nicht – nur, dass
  die Zusammenhänge überhaupt hergestellt werden.

Begriffe werden kleingeschrieben als Teilzeichenkette gesucht – im Deutschen nötig, weil
„planung“ sonst nicht in „Fassadenplanung“ gefunden würde. Nur vor Zahlen darf keine
weitere Ziffer stehen („5 at“ soll nicht „15 AT“ treffen). Ein Tupel ist eine Gruppe von
Alternativen; alle Gruppen einer Regel müssen vorkommen.

Bei Änderungen am Generator (scripts/generate_sample_documents.py) hier nachziehen.
"""

from dataclasses import dataclass

from search_cases import BG, KORR, P23, P24, P25, PLAN, SB08, SB09, row

Terms = tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class Finding:
    """Ein eingebauter Sachverhalt (S1–S6). Gefunden, wenn ein Risiko die Begriffe enthält
    **und** mindestens eine der erwarteten Fundstellen zitiert."""

    label: str
    terms: Terms
    locations: frozenset[tuple[str, str]]


@dataclass(frozen=True)
class Link:
    """Ein Zusammenhang, der erst beim Kombinieren sichtbar wird. Erkannt, wenn **ein**
    Risiko alle Begriffe enthält – im ganzen Risiko oder nur in den Unsicherheiten."""

    label: str
    terms: Terms
    only_uncertainties: bool = False


@dataclass(frozen=True)
class Distractor:
    """Ein erledigter Punkt. Verstoß, wenn Titel, Beschreibung oder Bereich eines Risikos ihn nennen."""

    label: str
    terms: Terms


def at(file_name: str, *locators: str) -> list[tuple[str, str]]:
    return [(file_name, locator) for locator in locators]


FINDINGS = [
    Finding(
        "S1 Genehmigung Haus B",
        (("genehmigung", "baugenehmigung", "bauantrag", "antrag"), ("haus b",)),
        frozenset(
            at(P24, "TOP 4")
            + at(SB09, "S. 1", "S. 2")
            + at(KORR, "S. 1", "S. 3")
            + at(BG, "S. 1")
            + at(PLAN, row("V07"))
        ),
    ),
    Finding(
        "S2 Fassadenplanung",
        (("fassade",), ("planung", "pläne", "plan", "werkplan")),
        frozenset(
            at(P23, "TOP 3")
            + at(P24, "TOP 3")
            + at(P25, "TOP 2")
            + at(SB09, "S. 2")
            + at(PLAN, row("V03"))
        ),
    ),
    Finding(
        "S3 Rohbauverzug",
        (("rohbau",), ("verzug", "verzöger", "verspät", "rückstand", "hinter")),
        frozenset(
            at(P23, "TOP 1")
            + at(P24, "TOP 1")
            + at(P25, "TOP 1")
            + at(SB08, "S. 1")
            + at(SB09, "S. 1", "S. 2")
            + at(PLAN, row("V02"))
        ),
    ),
    Finding(
        "S4 Nachtrag N-07",
        (("n-07",),),
        frozenset(at(P25, "TOP 2") + at(SB09, "S. 3", "S. 4")),
    ),
    Finding(
        "S5 Brandschutz ohne Verantw.",
        (("brandschutz",), ("verantwortlich", "zuständig", "benannt", "beauftrag")),
        frozenset(
            at(P23, "TOP 2")
            + at(P24, "TOP 2")
            + at(P25, "TOP 3")
            + at(SB09, "S. 1", "S. 4")
            + at(PLAN, row("V06"))
        ),
    ),
    Finding(
        "S6 Baubeginn Haus B",
        (("baubeginn",), ("haus b", "12.10")),
        frozenset(
            at(P24, "TOP 4")
            + at(P25, "TOP 4")
            + at(SB09, "S. 1", "S. 2")
            + at(PLAN, row("V08"))
        ),
    ),
]

LINKS = [
    Link(
        "Kette Brandschutz→Genehmigung→Baubeginn",
        (("brandschutz",), ("genehmigung", "antrag"), ("baubeginn",)),
    ),
    Link(
        "Frist 30.09. + 4 Wochen → 12.10. unhaltbar",
        (("30.09",), ("4 wochen", "vier wochen"), ("12.10", "baubeginn")),
    ),
    Link(
        "Kette Dämmung→Fassadenplanung→N-07",
        (("dämmung", "nichtbrennbar", "mineralwolle"), ("fassade",), ("n-07",)),
    ),
    Link(
        "Rohbauverzug 5 AT → 2 Wochen",
        (
            ("5 arbeitstag", "fünf arbeitstag", "5 at"),
            ("2 wochen", "zwei wochen", "10 arbeitstag"),
        ),
    ),
    Link(
        "Schätzung 4–6 Wochen als Unsicherheit",
        (("4 bis 6", "4-6", "4–6", "vier bis sechs"),),
        only_uncertainties=True,
    ),
]

DISTRACTORS = [
    Distractor("Kran / Sondernutzung", (("kran", "sondernutzung"),)),
    Distractor("N-05 beauftragt", (("n-05",),)),
    Distractor("SiGeKo-Begehung", (("sigeko",),)),
    Distractor("Kanalanschluss", (("kanal",),)),
    Distractor("Standsicherheitsnachweis", (("standsicherheit",),)),
]

FOREIGN_TERMS: tuple[str, ...] = ("grundschule", "dr. keller", "n-02", "aufzugsanlage")
"""Begriffe, die nur in BAU-43 vorkommen. „Aufzug“ allein taugt nicht: BAU-42 hat den
Nachtrag N-06 „Aufzugsunterfahrt“."""
