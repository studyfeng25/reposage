"""Generate human-readable Markdown wiki — content is written by the calling LLM via MCP tools."""
import logging
from pathlib import Path
from typing import List, Dict

logger = logging.getLogger(__name__)

MODULE_PROMPT = """\
You are a senior mobile engineer writing documentation for a codebase.
Given the following module information, write a concise Markdown document.

Module: {module_name}
Files: {files}

Key symbols:
{symbols}

Key relationships (calls/inherits):
{relations}

Write a Markdown document with:
1. A one-paragraph description of this module's responsibility
2. Key classes/protocols/functions with a one-line description each
3. A "How it works" section describing the main flow (2-4 sentences)
4. A Mermaid diagram showing the main class relationships (if applicable)

Be concise. No boilerplate. Focus on what matters for understanding and modifying this code.
"""

ARCH_PROMPT = """\
You are a senior mobile engineer writing architecture documentation.
Given the following module summaries for the repository "{repo_name}", write a top-level ARCHITECTURE.md.

Modules:
{modules}

Write:
1. A 2-paragraph overview of what this codebase does
2. A module dependency diagram in Mermaid (flowchart TD)
3. A table of modules with their responsibilities
4. Key architectural patterns used (e.g., MVVM, delegation, notification center)

Be concise and actionable. Focus on helping a new engineer understand the codebase quickly.
"""


class WikiGenerator:
    def __init__(self, repo_root: Path, db=None):
        from reposage.indexer.pipeline import get_reposage_dir
        self.repo_root = repo_root
        reposage_dir = get_reposage_dir(repo_root)
        self.docs_dir = reposage_dir / "docs"
        self.docs_dir.mkdir(parents=True, exist_ok=True)
        (self.docs_dir / "modules").mkdir(exist_ok=True)

        if db is None:
            from reposage.storage.db import RepoSageDB
            db_path = reposage_dir / "index.db"
            db = RepoSageDB(db_path)
        self.db = db

    def generate(self, force: bool = False):
        """Generate fallback wiki docs (symbol listings) for all modules.

        Full LLM-generated docs are produced by the Agent via the MCP tools
        get_pending_wiki / write_wiki — no API key required.
        """
        modules = self.db.get_all_modules()
        for module in modules:
            md_path = self.docs_dir / "modules" / f"{module['name']}.md"
            if md_path.exists() and not force:
                continue
            content = self._fallback_module_doc(module)
            md_path.write_text(content, encoding="utf-8")
            logger.info(f"Generated fallback wiki for module: {module['name']}")

        arch_path = self.docs_dir / "ARCHITECTURE.md"
        if not arch_path.exists() or force:
            arch_path.write_text(self._fallback_architecture(), encoding="utf-8")
            logger.info("Generated fallback ARCHITECTURE.md")

    def _fallback_module_doc(self, module: Dict) -> str:
        rows = self.db.conn.execute(
            """SELECT name, type, file, start_line FROM symbols
               WHERE module_id = ? AND is_public = 1
               ORDER BY type, name LIMIT 40""",
            (module["id"],),
        ).fetchall()
        lines = [f"# {module['name']}\n", f"**Files**: {', '.join(module['files'][:5])}\n"]
        if rows:
            lines.append("## Symbols\n")
            for r in rows:
                lines.append(f"- `{r['name']}` ({r['type']}) — {r['file']}:{r['start_line']}")
        return "\n".join(lines)

    def _fallback_architecture(self) -> str:
        modules = self.db.get_all_modules()
        lines = [f"# {self.repo_root.name} Architecture\n", "## Modules\n"]
        for m in modules:
            lines.append(f"- **{m['name']}** — {', '.join(m['files'][:3])}")
        return "\n".join(lines)
