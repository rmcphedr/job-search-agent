"""Synchronize and load the generated local copy of the master career profile."""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from src.database.db import get_project_root

GENERATED_HEADER = """<!-- GENERATED FILE — DO NOT EDIT MANUALLY.
Source: {source}
Source SHA-256: {source_hash}
Synchronized at: {synchronized_at}
Regenerate with: python3 -m src.profile.master_profile
-->

"""
HASH_PATTERN = re.compile(r"^Source SHA-256: ([0-9a-f]{64})$", re.MULTILINE)
HEADER_END = "-->\n\n"


def _sync_config(project_root: Path | None = None) -> tuple[Path, Path]:
    root = project_root or get_project_root()
    config_path = root / "config" / "profile.yml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    sync = config.get("master_profile_sync", {})
    if not isinstance(sync, dict):
        raise RuntimeError("config/profile.yml: master_profile_sync must be a mapping")

    source_value = sync.get("source_path")
    destination_value = sync.get("destination_path")
    if not source_value or not destination_value:
        raise RuntimeError("config/profile.yml must define master_profile_sync source_path and destination_path")

    source = (root / str(source_value)).resolve()
    destination = (root / str(destination_value)).resolve()
    return source, destination


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _source_content(project_root: Path | None = None) -> tuple[Path, str]:
    source, _ = _sync_config(project_root)
    if not source.is_file():
        raise FileNotFoundError(f"Master profile source not found: {source}")
    return source, source.read_text(encoding="utf-8")


def sync_master_profile(project_root: Path | None = None) -> Path:
    """Copy the canonical profile into user/master_cv.md with provenance metadata."""
    root = project_root or get_project_root()
    source, content = _source_content(root)
    _, destination = _sync_config(root)
    source_label = Path(source).relative_to(root.parent).as_posix()
    header = GENERATED_HEADER.format(
        source=source_label,
        source_hash=_sha256(content),
        synchronized_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(header + content, encoding="utf-8")
    return destination


def sync_status(project_root: Path | None = None) -> tuple[bool, str]:
    """Return whether the generated copy matches the current canonical source."""
    root = project_root or get_project_root()
    source, source_content = _source_content(root)
    _, destination = _sync_config(root)
    if not destination.is_file():
        return False, f"Generated profile is missing: {destination}"

    generated = destination.read_text(encoding="utf-8")
    match = HASH_PATTERN.search(generated)
    if not match:
        return False, f"Generated profile has no synchronization hash: {destination}"
    if match.group(1) != _sha256(source_content):
        return False, f"Generated profile is stale; source changed: {source}"
    if HEADER_END not in generated or generated.split(HEADER_END, 1)[1] != source_content:
        return False, f"Generated profile content was modified manually: {destination}"
    return True, "Master profile is synchronized"


def load_master_profile(project_root: Path | None = None, *, warn_if_stale: bool = True) -> str:
    """Load the generated profile and warn if it is missing, stale, or modified."""
    root = project_root or get_project_root()
    _, destination = _sync_config(root)
    current, message = sync_status(root)
    if warn_if_stale and not current:
        print(f"WARNING: {message}. Run: python3 -m src.profile.master_profile", file=sys.stderr)
    if not destination.is_file():
        raise FileNotFoundError(message)
    content = destination.read_text(encoding="utf-8")
    return content.split(HEADER_END, 1)[-1]


def master_profile_hash(project_root: Path | None = None) -> str:
    """Hash the profile text used for evaluation and cache invalidation."""
    return _sha256(load_master_profile(project_root))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the generated copy is stale")
    args = parser.parse_args(argv)
    if args.check:
        current, message = sync_status()
        print(message)
        return 0 if current else 1
    print(f"Synchronized master profile to {sync_master_profile()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
