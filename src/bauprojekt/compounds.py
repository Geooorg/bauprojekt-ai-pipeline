"""Zusammengesetzte Wörter zerlegen – für die Volltextsuche.

Postgres bildet Stammformen, zerlegt aber keine Komposita: „Genehmigungen“ wird zu
``genehm``, „Baugenehmigung“ zu ``baugenehm``. Im Deutschen ist das der Normalfall, und
die Volltextsuche findet dann die Hälfte nicht.

Lösung: Die Teile eines Kompositums werden *zusätzlich* indiziert. Aus „Baugenehmigung“
wird der Zusatz „bau genehmigung“. Das Originalwort bleibt im Index. Eine falsche
Zerlegung erzeugt deshalb höchstens einen überflüssigen Suchbegriff – sie kann keinen
Treffer verhindern.

Zerlegt wird statistisch mit CharSplit (Tuggener 2016): Das Verfahren hat aus einem
großen Korpus gelernt, an welchen Buchstabenfolgen deutsche Wörter typischerweise
zusammengesetzt sind.

Regel: Die beste Zerlegung gilt nur ab einer Punktzahl von 0,6. Darunter liegen richtige
und falsche Zerlegungen durcheinander – „Fassaden + dämmung“ (−0,79) neben
„Bear + beitung“ (−0,80), „Wohn + quartier“ (0,49) neben „Unter + lagen“ (0,57). Keine
Schwelle trennt sie. Ab 0,6 stimmt die Zerlegung fast immer.

Falsche Zerlegungen sind nicht harmlos: Sie fügen Wörter wie „ständig“ oder „reicht“ in
den Index ein, und die erzeugen falsche Volltexttreffer. Deshalb gilt Genauigkeit vor
Vollständigkeit – „Fassadendämmung“ wird nicht zerlegt. Das ist eine bekannte Grenze.

Teile mit 3 Buchstaben („Bau“) sind nur auf der obersten Ebene erlaubt. Tiefer unten
sind es fast immer Vorsilben: „Auf + sicht“, „Ver + trag“.

Lizenz: ``compound-split`` steht unter GPL-3.0. Es wird nur hier verwendet, damit es
sich ersetzen lässt (etwa durch Hunspell-Wörterbücher in Postgres).
"""

import re
from functools import lru_cache

from compound_split import char_split

MIN_WORD_LENGTH = 7
"""Kürzere Wörter werden nicht zerlegt."""

MIN_SCORE = 0.6
"""Ab hier stimmt die Zerlegung fast immer. Abgeleitet aus allen 160 Wörtern der Testdaten,
die das Verfahren zerlegen würde: darunter halb richtig, halb Unsinn."""

MIN_PART_LENGTH = 3
"""Kürzere Teile werden nie abgetrennt."""

MIN_NESTED_PART_LENGTH = 4
"""Beim Weiterzerlegen von Teilen: 3 Buchstaben sind dort fast immer Vorsilben."""

WORD_PATTERN = re.compile(r"[^\W\d_]+")
"""Nur Buchstabenfolgen. Zahlen, Aktenzeichen und Nachtragsnummern bleiben unberührt."""


@lru_cache(maxsize=10_000)
def split_compound(word: str, *, nested: bool = False) -> list[str]:
    """Kompositum in seine Teile zerlegen (klein geschrieben), mehrteilige rekursiv.

    Zwischenteile bleiben erhalten: „Brandschutzprüfung“ ergibt
    ``brandschutz, brand, schutz, prüfung``. Kein Kompositum ergibt eine leere Liste.
    """
    if len(word) < MIN_WORD_LENGTH:
        return []

    score, head, tail = char_split.split_compound(word)[0]
    min_part = MIN_NESTED_PART_LENGTH if nested else MIN_PART_LENGTH
    if score < MIN_SCORE or min(len(head), len(tail)) < min_part:
        return []

    parts: list[str] = []
    for part in (head, tail):
        parts.append(part.lower())
        parts.extend(split_compound(part, nested=True))
    return parts


def compound_parts(text: str) -> str:
    """Die Teile aller Komposita eines Textes, durch Leerzeichen getrennt und ohne Dubletten."""
    seen: dict[str, None] = {}
    for word in WORD_PATTERN.findall(text):
        for part in split_compound(word):
            seen.setdefault(part)
    return " ".join(seen)
