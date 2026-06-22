"""Load directory source configuration."""

from __future__ import annotations

from pathlib import Path

import yaml

from src.database.db import get_project_root
from src.discovery.models import DirectorySource

CONFIG_PATH = get_project_root() / "config" / "directory_sources.yaml"


def load_directory_sources(
    config_path: Path | None = None,
    source_id: str | None = None,
) -> list[DirectorySource]:
    """Load directory sources from YAML, optionally filtered by source_id."""
    path = config_path or CONFIG_PATH
    if not path.exists():
        raise FileNotFoundError(f"Directory sources config not found: {path}")

    try:
        with path.open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as exc:
        raise RuntimeError(f"Failed to load directory sources from {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise RuntimeError(f"Directory sources config must be a mapping: {path}")

    raw_sources = data.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise RuntimeError(f"Directory sources config must contain a non-empty 'sources' list: {path}")

    sources: list[DirectorySource] = []
    for index, raw_source in enumerate(raw_sources, start=1):
        if not isinstance(raw_source, dict):
            raise RuntimeError(f"Source entry #{index} in {path} must be a mapping.")
        try:
            sources.append(DirectorySource.model_validate(raw_source))
        except Exception as exc:
            raise RuntimeError(f"Invalid source entry #{index} in {path}: {exc}") from exc

    if source_id is not None:
        filtered = [source for source in sources if source.source_id == source_id]
        if not filtered:
            known = ", ".join(source.source_id for source in sources)
            raise ValueError(
                f"Unknown source_id {source_id!r}. Available sources: {known}"
            )
        return filtered

    return sources
