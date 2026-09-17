"""Aufteilung der Segmente in Chunks – die Einheiten, die eingebettet und durchsucht werden.

Reine Funktionen ohne Dateisystem-Zugriff.

Drei Regeln bestimmen das Ergebnis:

1. **Ein Chunk gehört zu genau einem Segment.** Er reicht nie über eine Seiten- oder
   TOP-Grenze hinweg, sonst wäre die Fundstelle im Quellenverweis mehrdeutig.
2. **Tabellenzeilen werden nie geteilt.** Thema, Sachstand und Verantwortlicher gehören
   zusammen; getrennt wären sie einzeln kaum noch zu deuten.
3. **Getrennt wird an Satz- und Absatzgrenzen**, mit Überlappung. Ein hart geschnittener
   Satz liefert weder ein brauchbares Embedding noch ein lesbares Zitat.

``char_start`` und ``char_end`` zeigen in den Text des Segments. Damit lässt sich zu jedem
Treffer der Zusammenhang anzeigen, ohne das Original erneut zu öffnen.
"""

import re

from bauprojekt.config import CHUNK_MAX_CHARS, CHUNK_OVERLAP_CHARS
from bauprojekt.models import Chunk, Document, Segment, SegmentKind

BOUNDARY_PATTERN = re.compile(r"\n+|(?<=[.!?:;])\s+")
"""Bevorzugte Trennstellen: Zeilenumbrüche und Satzzeichen, denen Leerraum folgt."""

UNSPLITTABLE_KINDS = frozenset({SegmentKind.TABELLENZEILE})
"""Segmentarten, die als Ganzes einen Chunk bilden, auch wenn sie lang sind."""


def chunk_segments(
    document: Document,
    segments: list[Segment],
    *,
    max_chars: int = CHUNK_MAX_CHARS,
    overlap: int = CHUNK_OVERLAP_CHARS,
) -> list[Chunk]:
    """Segmente eines Dokuments in Chunks überführen. Der Index läuft über das ganze Dokument."""
    chunks: list[Chunk] = []
    for segment in segments:
        spans = (
            [(0, len(segment.text))]
            if segment.kind in UNSPLITTABLE_KINDS
            else split_spans(segment.text, max_chars=max_chars, overlap=overlap)
        )
        for char_start, char_end in spans:
            chunks.append(
                Chunk.create(
                    document=document,
                    segment=segment,
                    index=len(chunks),
                    text=segment.text[char_start:char_end],
                    char_start=char_start,
                    char_end=char_end,
                )
            )
    return chunks


def split_spans(text: str, *, max_chars: int, overlap: int) -> list[tuple[int, int]]:
    """Textbereiche bestimmen, die höchstens ``max_chars`` lang sind.

    Bevorzugt wird die letzte Trennstelle innerhalb der Obergrenze. Gibt es keine – etwa in
    einer sehr langen Aufzählung ohne Satzzeichen – wird hart geschnitten.
    """
    if len(text) <= max_chars:
        return [(0, len(text))]

    boundaries = [match.end() for match in BOUNDARY_PATTERN.finditer(text)]
    spans: list[tuple[int, int]] = []
    start = 0

    while start < len(text):
        limit = start + max_chars
        if limit >= len(text):
            spans.append(trim(text, start, len(text)))
            break

        candidates = [boundary for boundary in boundaries if start < boundary <= limit]
        end = max(candidates) if candidates else limit
        spans.append(trim(text, start, end))
        start = next_start(
            text, boundaries, end=end, previous_start=start, overlap=overlap
        )

    return spans


def next_start(
    text: str, boundaries: list[int], *, end: int, previous_start: int, overlap: int
) -> int:
    """Startpunkt des nächsten Chunks: um die Überlappung zurück, dann auf eine Satzgrenze.

    So beginnt auch der überlappende Teil mit einem vollständigen Satz. Ein Chunk, der
    mitten im Satz anfängt, liefert ein schlechteres Embedding und ein unbrauchbares Zitat.
    Fehlt eine Satzgrenze, genügt die nächste Wortgrenze.
    """
    target = max(end - overlap, previous_start + 1)
    candidates = [b for b in boundaries if previous_start < b <= target]
    if candidates:
        return max(candidates)

    start = target
    while start < end and not text[start - 1].isspace():
        start += 1
    return start


def trim(text: str, start: int, end: int) -> tuple[int, int]:
    """Führenden und folgenden Leerraum aus dem Bereich nehmen, damit Offsets und Text zueinander passen."""
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end
