# bauprojekt-ai-pipeline

Lernprojekt: Baudokumente einlesen, als Parquet speichern, semantisch durchsuchen und quellenbasierte Risikoberichte erzeugen.

- Produktvision: [docs/produktvision.md](docs/produktvision.md)
- Testdaten und die bekannte Wahrheit dazu: [docs/testdaten.md](docs/testdaten.md)
- Arbeitsregeln und Phasen: [CLAUDE.md](CLAUDE.md)

## Schnellstart

```bash
uv sync
uv run python scripts/generate_sample_documents.py   # synthetische Projekte BAU-42 und BAU-43
podman compose -f infra/docker-compose.yml up -d      # ab Phase 2
```
