"""Full indexing pipeline: parse → store → resolve → embed → generate."""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional


def get_reposage_dir(repo_root: Path) -> Path:
    """Return the RepoSage data directory for a repo (sibling dir, not inside repo)."""
    return repo_root.parent / f"RepoSage-{repo_root.name}"

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

logger = logging.getLogger(__name__)
console = Console()


class IndexPipeline:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.reposage_dir = get_reposage_dir(repo_root)
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

        self.db.set_meta("last_indexed", datetime.now().isoformat())
        stats = self.db.get_stats()
        console.print(f"\n[bold green]Done![/bold green]  "
                      f"Symbols: {stats['symbols']}  "
                      f"Relations: {stats['relations']}  "
                      f"Modules: {stats['modules']}")

        self._write_pending_llm()

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
        console.print(f"  Agent index written to RepoSage-{self.repo_root.name}/")

    def _write_pending_llm(self):
        """Write pending LLM task counts and print instructions for Claude."""
        symbol_count = self.db.conn.execute(
            "SELECT COUNT(*) FROM symbols WHERE summary IS NULL OR summary = ''"
        ).fetchone()[0]

        modules = self.db.get_all_modules()
        docs_dir = self.reposage_dir / "docs" / "modules"
        module_count = sum(
            1 for m in modules
            if not (docs_dir / f"{m['name']}.md").exists()
        )
        arch_missing = not (self.reposage_dir / "docs" / "ARCHITECTURE.md").exists()

        pending = {
            "symbol_count": symbol_count,
            "module_count": module_count,
            "architecture_missing": arch_missing,
            "generated_at": datetime.now().isoformat(),
        }
        pending_path = self.reposage_dir / "pending_llm.json"
        with open(pending_path, "w") as f:
            json.dump(pending, f, indent=2)

        if symbol_count > 0 or module_count > 0 or arch_missing:
            console.print("\n[bold yellow]LLM tasks pending[/bold yellow]")
            if symbol_count > 0:
                console.print(f"  Symbols without summary : {symbol_count}")
            if module_count > 0:
                console.print(f"  Modules without wiki    : {module_count}")
            if arch_missing:
                console.print(f"  ARCHITECTURE.md missing : yes")
            console.print(
                "\n  Ask Claude to complete these tasks:\n"
                '  [italic]"请调用 get_pending_summaries 和 get_pending_wiki 工具完成 RepoSage 的 LLM 生成阶段"[/italic]'
            )
