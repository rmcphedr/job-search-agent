"""Watch staging directories and merge new files automatically."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from src.orchestration.handlers import merge_staging_file
from src.orchestration.manifest import is_file_processed, load_manifest
from src.orchestration.paths import get_runs_root, infer_run_id_from_path

logger = logging.getLogger(__name__)


class StagingMergeHandler(FileSystemEventHandler):
    """Merge JSON staging files when created or modified under runs/."""

    def __init__(self, *, force_re_eval: bool = False, settle_seconds: float = 0.5) -> None:
        super().__init__()
        self.force_re_eval = force_re_eval
        self.settle_seconds = settle_seconds
        self._pending: dict[str, float] = {}

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        self._schedule(Path(event.src_path))

    def on_modified(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        self._schedule(Path(event.src_path))

    def _schedule(self, path: Path) -> None:
        if path.suffix.lower() != ".json":
            return
        if path.name == "manifest.json":
            return
        if "rejected" in path.parts:
            return
        self._pending[str(path.resolve())] = time.monotonic()

    def process_pending(self) -> list[dict]:
        """Process files whose settle window has elapsed."""
        now = time.monotonic()
        ready = [
            Path(key)
            for key, scheduled_at in list(self._pending.items())
            if now - scheduled_at >= self.settle_seconds
        ]
        results: list[dict] = []
        for path in ready:
            self._pending.pop(str(path.resolve()), None)
            if not path.exists():
                continue
            run_id = infer_run_id_from_path(path)
            if run_id:
                manifest = load_manifest(run_id)
                if manifest and is_file_processed(manifest, path):
                    continue
            try:
                result = merge_staging_file(path, force_re_eval=self.force_re_eval)
                results.append(result.to_dict())
                logger.info(
                    "Merged %s → %s (%s)",
                    path.name,
                    result.action,
                    result.company_name or result.skipped_reason,
                )
            except Exception as exc:
                logger.exception("Failed to merge %s: %s", path, exc)
                results.append({"success": False, "path": str(path), "error": str(exc)})
        return results


def scan_existing_files(handler: StagingMergeHandler, runs_root: Path) -> list[dict]:
    """Process any JSON files already present (startup catch-up)."""
    results: list[dict] = []
    if not runs_root.exists():
        return results

    for path in sorted(runs_root.rglob("*.json")):
        if path.name == "manifest.json" or "rejected" in path.parts:
            continue
        handler._schedule(path)  # noqa: SLF001 — startup batch uses same settle path
    return handler.process_pending()


def run_watcher(
    *,
    runs_root: Path | None = None,
    force_re_eval: bool = False,
    poll_interval: float = 1.0,
    settle_seconds: float = 0.5,
    once: bool = False,
) -> None:
    root = runs_root or get_runs_root()
    root.mkdir(parents=True, exist_ok=True)

    handler = StagingMergeHandler(force_re_eval=force_re_eval, settle_seconds=settle_seconds)
    scan_existing_files(handler, root)

    if once:
        handler.process_pending()
        return

    observer = Observer()
    observer.schedule(handler, str(root), recursive=True)
    observer.start()
    logger.info("Watching %s for staging files...", root)

    try:
        while True:
            handler.process_pending()
            time.sleep(poll_interval)
    except KeyboardInterrupt:
        logger.info("Stopping staging watcher.")
    finally:
        observer.stop()
        observer.join()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Watch staging runs and merge JSON files.")
    parser.add_argument(
        "--runs-root",
        type=Path,
        default=None,
        help="Override runs directory (default: data/staging/runs).",
    )
    parser.add_argument(
        "--force-re-eval",
        action="store_true",
        help="Allow evaluation merges for companies already evaluated.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process existing files and exit (no continuous watch).",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=1.0,
        help="Seconds between pending-file scans (default: 1.0).",
    )
    parser.add_argument(
        "--settle-seconds",
        type=float,
        default=0.5,
        help="Wait after file change before merging (default: 0.5).",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    try:
        run_watcher(
            runs_root=args.runs_root,
            force_re_eval=args.force_re_eval,
            poll_interval=args.poll_interval,
            settle_seconds=args.settle_seconds,
            once=args.once,
        )
    except Exception as exc:
        logger.exception("Watcher failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
