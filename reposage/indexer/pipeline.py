"""Full indexing pipeline: parse → store → resolve → embed → generate."""
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

logger = logging.getLogger(__name__)
console = Console()


class IndexPipeline:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.reposage_dir = repo_root / ".reposage"
        self.reposage_dir.mkdir(exist_ok=True)

        from reposage.storage.db import RepoSageDB
        from reposage.storage.vector_store import VectorStore

        self.db = RepoSageDB(self.reposage_dir / "index.db")
        self.vector_store = VectorStore(
            self.reposage_dir / "vectors",
            repo_root.name,
        )

    def run(self, force: bool = False, skip_wiki: bool = False,
            skip_embed: bool = False):
        """Run the full indexing pipeline."""
        console.print("[bold]RepoSage Indexer[/bold]")
        console.print(f"  Repo: {self.repo_root}")

        # Phase 1: Parse all source files
        self._phase_parse(force=force)

        # Phase 2: Resolve cross-file relations
        self._phase_resolve()

        # Phase 3: Cluster into modules
        self._phase_cluster()

        # Phase 4: Embed symbols
        if not skip_embed:
            self._phase_embed()

        # Phase 5: Generate agent index
        self._phase_agent_index()

        # Phase 6: Generate wiki (calls Claude API)
        if not skip_wiki:
            self._phase_wiki()

        self.db.set_meta("last_indexed", datetime.now().isoformat())
        stats = self.db.get_stats()
        console.print(f"\n[bold green]Done![/bold green]  "
                      f"Symbols: {stats['symbols']}  "
                      f"Relations: {stats['relations']}  "
                      f"Modules: {stats['modules']}")

    def index_file(self, file_path: Path):
        """Incrementally index a single file (called by watcher)."""
        from reposage.indexer.parser import parse_file, detect_language

        if not detect_language(str(file_path)):
            return

        rel = str(file_path.relative_to(self.repo_root))
        self.db.delete_symbols_for_file(rel)

        symbols, relations = parse_file(file_path, self.repo_root)
        if symbols:
            self.db.upsert_symbols(symbols)
        if relations:
            self.db.upsert_relations(relations)

        self.db.resolve_relations()

        # Update embeddings for changed file
        sym_dicts = self.db.get_symbols_for_file(rel)
        if sym_dicts:
            self.vector_store.upsert_symbols(sym_dicts)

        # Regenerate agent index
        from reposage.generator.agent_index import AgentIndexGenerator
        AgentIndexGenerator(self.repo_root, self.db).generate()

        logger.info(f"Re-indexed {rel}: {len(symbols)} symbols")

    # ── Phases ────────────────────────────────────────────────────────────────

    def _phase_parse(self, force: bool = False):
        from reposage.indexer.parser import iter_source_files, parse_file

        already_indexed = set(self.db.get_indexed_files()) if not force else set()
        files = list(iter_source_files(self.repo_root))

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Parsing files...", total=len(files))
            total_symbols = 0
            total_relations = 0

            for file_path in files:
                rel = str(file_path.relative_to(self.repo_root))
                progress.update(task, description=f"Parsing {file_path.name}")

                if rel in already_indexed and not force:
                    progress.advance(task)
                    continue

                symbols, relations = parse_file(file_path, self.repo_root)
                if symbols:
                    self.db.upsert_symbols(symbols)
                    total_symbols += len(symbols)
                if relations:
                    self.db.upsert_relations(relations)
                    total_relations += len(relations)

                progress.advance(task)

        console.print(f"  Parsed {len(files)} files → "
                      f"{total_symbols} symbols, {total_relations} relations")

    def _phase_resolve(self):
        from reposage.indexer.resolver import resolve_relations
        resolved = resolve_relations(self.db)
        console.print(f"  Resolved {resolved} cross-file relations")

    def _phase_cluster(self):
        from reposage.indexer.resolver import cluster_files_into_modules
        modules = cluster_files_into_modules(self.db)
        for m in modules:
            self.db.upsert_module(m["id"], m["name"], m["files"])
        console.print(f"  Clustered into {len(modules)} modules")

    def _phase_embed(self):
        symbols = self.db.get_all_symbols()
        if not symbols:
            return
        console.print(f"  Embedding {len(symbols)} symbols...")
        BATCH = 200
        for i in range(0, len(symbols), BATCH):
            batch = symbols[i:i + BATCH]
            self.vector_store.upsert_symbols(batch)
        console.print(f"  Embedded {len(symbols)} symbols")

    def _phase_agent_index(self):
        from reposage.generator.agent_index import AgentIndexGenerator
        gen = AgentIndexGenerator(self.repo_root, self.db)
        gen.generate()
        console.print(f"  Agent index written to .reposage/")

    def _phase_wiki(self):
        import os
        if not os.environ.get("ANTHROPIC_API_KEY"):
            console.print("  [yellow]Skipping wiki: ANTHROPIC_API_KEY not set[/yellow]")
            return
        from reposage.generator.wiki import WikiGenerator
        gen = WikiGenerator(self.repo_root, self.db)
        gen.generate()
        console.print(f"  Wiki written to docs/")
