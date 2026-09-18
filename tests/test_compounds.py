"""Tests für bauprojekt.compounds."""

import pytest

from bauprojekt.compounds import compound_parts, split_compound


class TestZerlegen:
    @pytest.mark.parametrize(
        ("wort", "teile"),
        [
            ("Baugenehmigung", ["bau", "genehmigung"]),
            ("Brandschutzprüfung", ["brandschutz", "brand", "schutz", "prüfung"]),
            ("Budgetreserve", ["budget", "reserve"]),
            ("Kanalanschluss", ["kanal", "anschluss"]),
            ("Bauherr", ["bau", "herr"]),
        ],
    )
    def test_typische_komposita(self, wort: str, teile: list[str]) -> None:
        assert split_compound(wort) == teile

    def test_bekannte_grenze_unsichere_zerlegung(self) -> None:
        """'Fassaden + dämmung' wäre richtig, hat aber −0,79 – so niedrig wie 'Bear + beitung'.

        Unterhalb von 0,6 ist das Verfahren unzuverlässig; Genauigkeit geht vor.
        """
        assert split_compound("Fassadendämmung") == []

    @pytest.mark.parametrize(
        "wort", ["Bearbeitung", "September", "Architekt", "Unterlagen"]
    )
    def test_unsinnige_zerlegungen_werden_verworfen(self, wort: str) -> None:
        """Aus dem echten Textbestand: 'Bear + beitung', 'Sept + ember', 'Archi + tekt'."""
        assert split_compound(wort) == []

    def test_zwischenteile_bleiben_erhalten(self) -> None:
        """'Brandschutz' soll auch als Ganzes gefunden werden, nicht nur 'Brand' und 'Schutz'."""
        assert "brandschutz" in split_compound("Brandschutzprüfung")

    def test_kurzer_teil_nur_bei_hoher_sicherheit(self) -> None:
        """'Bau' hat 3 Buchstaben – erlaubt, weil sicher (0,92). 'Gen' (−0,55) nicht."""
        assert split_compound("Bauaufsicht") == ["bau", "aufsicht"]
        assert split_compound("Genehmigung") == []

    @pytest.mark.parametrize("wort", ["Genehmigung", "Verantwortlicher", "Frist"])
    def test_keine_komposita(self, wort: str) -> None:
        """'Gen' + 'ehmigung', 'Ver' + 'antwortlicher': ein Teil zu kurz, also keine Zerlegung."""
        assert split_compound(wort) == []


class TestTextErweitern:
    def test_liefert_nur_die_teile(self) -> None:
        """Das Originalwort steht schon im Text – ergänzt werden nur die Teile."""
        assert compound_parts("Die Baugenehmigung fehlt.") == "bau genehmigung"

    def test_ohne_komposita_leer(self) -> None:
        assert compound_parts("Der Antrag ruht.") == ""

    def test_doppelte_teile_nur_einmal(self) -> None:
        assert (
            compound_parts("Baugenehmigung und Teilbaugenehmigung")
            .split()
            .count("genehmigung")
            == 1
        )

    def test_zahlen_und_kennungen_bleiben_unberuehrt(self) -> None:
        assert compound_parts("N-07 BA-2026-0587 48.500 EUR") == ""
