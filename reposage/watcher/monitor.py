"""File watcher: monitors source files and triggers incremental re-indexing."""
import logging
import time
from pathlib import Path
from threading import Timer, Lock
from typing import Optional, Set

from watchdog.events import FileSystemEventHandler, FileSystemEvent
from watchdog.observers import Observer

from reposage.indexer.parser import ALL_EXTENSIONS

logger = logging.getLogger(__name__)

DEBOUNCE_SECONDS = 0.5
EXCLUDE_DIRS = {
    ".git", "node_modules", "Pods", "build", "DerivedData",
    ".build", "vendor", "__pycache__", ".reposage",
}


class _Handler(FileSystemEventHandler):
    def __init__(self, repo_root: Path, pipeline):
        self.repo_root = repo_root
        self.pipeline = pipeline
        self._pending: Set[str] = set()
        self._timer: Optional[Timer] = None
        self._lock = Lock()

    def _is_relevant(self, path: str) -> bool:
        p = Path(path)
        if p.suffix.lower() not in ALL_EXTENSIONS:
            return False
        if any(part in EXCLUDE_DIRS for part in p.parts):
            return False
        return True

    def _schedule(self, path: str):
        with self._lock:
            self._pending.add(path)
            if self._timer:
                self._timer.cancel()
            self._timer = Timer(DEBOUNCE_SECONDS, self._flush)
            self._timer.start()

    def _flush(self):
        with self._lock:
            files = list(self._pending)
            self._pending.clear()
            self._timer = None

        for path in files:
            try:
                self.pipeline.index_file(Path(path))
                logger.info(f"Re-indexed: {path}")
            except Exception as e:
                logger.warning(f"Re-index failed for {path}: {e}")

    def on_modified(self, event: FileSystemEvent):
        if not event.is_directory and self._is_relevant(event.src_path):
            self._schedule(event.src_path)

    def on_created(self, event: FileSystemEvent):
        if not event.is_directory and self._is_relevant(event.src_path):
            self._schedule(event.src_path)

    def on_deleted(self, event: FileSystemEvent):
        if not event.is_directory and self._is_relevant(event.src_path):
            p = Path(event.src_path)
            rel = str(p.relative_to(self.repo_root))
            try:
                self.pipeline.db.delete_symbols_for_file(rel)
                logger.info(f"Removed index for deleted file: {rel}")
            except Exception as e:
                logger.warning(f"Cleanup failed for {rel}: {e}")

    def on_moved(self, event: FileSystemEvent):
        # Treat as delete + create
        self.on_deleted(type("E", (), {"is_directory": False, "src_path": event.src_path})())
        self.on_created(type("E", (), {"is_directory": False, "src_path": event.dest_path})())


def start_watcher(repo_root: Path):
    """Start watching a repository for file changes. Blocks until Ctrl-C."""
    from reposage.indexer.pipeline import IndexPipeline
    from rich.console import Console

    console = Console()

    db_path = repo_root / ".reposage" / "index.db"
    if not db_path.exists():
        console.print("[yellow]Repository not indexed yet. Running initial analysis...[/yellow]")
        pipeline = IndexPipeline(repo_root)
        pipeline.run(skip_wiki=True)
    else:
        pipeline = IndexPipeline(repo_root)

    handler = _Handler(repo_root, pipeline)
    observer = Observer()
    observer.schedule(handler, str(repo_root), recursive=True)
    observer.start()

    console.print(f"[bold green]Watching[/bold green] {repo_root}")
    console.print("Press Ctrl+C to stop.\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
    console.print("Watcher stopped.")
