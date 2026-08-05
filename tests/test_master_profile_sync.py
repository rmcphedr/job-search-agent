from pathlib import Path

import yaml

from src.profile.master_profile import load_master_profile, sync_master_profile, sync_status


def _project(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "job-search-agent"
    source = tmp_path / "resume-generation-pipeline" / "personal" / "master-profile.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Canonical profile\n\nConfirmed evidence.\n", encoding="utf-8")
    (root / "config").mkdir(parents=True)
    (root / "user").mkdir()
    config = {
        "master_profile_sync": {
            "source_path": "../resume-generation-pipeline/personal/master-profile.md",
            "destination_path": "user/master_cv.md",
        }
    }
    (root / "config" / "profile.yml").write_text(yaml.safe_dump(config), encoding="utf-8")
    return root, source


def test_sync_copies_profile_and_records_provenance(tmp_path: Path) -> None:
    root, _ = _project(tmp_path)

    destination = sync_master_profile(root)

    assert "GENERATED FILE — DO NOT EDIT MANUALLY" in destination.read_text(encoding="utf-8")
    assert load_master_profile(root) == "# Canonical profile\n\nConfirmed evidence.\n"
    assert sync_status(root)[0] is True


def test_check_detects_changed_source(tmp_path: Path) -> None:
    root, source = _project(tmp_path)
    sync_master_profile(root)
    source.write_text("# Changed\n", encoding="utf-8")

    current, message = sync_status(root)

    assert current is False
    assert "stale" in message


def test_check_detects_manual_destination_edit(tmp_path: Path) -> None:
    root, _ = _project(tmp_path)
    destination = sync_master_profile(root)
    destination.write_text(destination.read_text(encoding="utf-8") + "manual edit\n", encoding="utf-8")

    current, message = sync_status(root)

    assert current is False
    assert "modified manually" in message
