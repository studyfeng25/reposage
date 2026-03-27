"""Generate human-readable Markdown wiki using Claude API."""
import logging
import os
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

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        self.client = None
        if api_key:
            import anthropic
            self.client = anthropic.Anthropic(api_key=api_key)

    def generate(self, force: bool = False):
        modules = self.db.get_all_modules()
        module_summaries = []

        for module in modules:
            md_path = self.docs_dir / "modules" / f"{module['name']}.md"
            if md_path.exists() and not force:
                # Read existing summary for arch doc
                existing = md_path.read_text(encoding="utf-8")
                module_summaries.append({
                    "name": module["name"],
                    "summary": existing[:500],
                })
                continue

            content = self._generate_module_doc(module)
            if content:
                md_path.write_text(content, encoding="utf-8")
                module_summaries.append({
                    "name": module["name"],
                    "summary": content[:500],
                })
                logger.info(f"Generated wiki for module: {module['name']}")

        # Generate top-level ARCHITECTURE.md
        arch_path = self.docs_dir / "ARCHITECTURE.md"
        if not arch_path.exists() or force:
            arch_content = self._generate_architecture(module_summaries)
            if arch_content:
                arch_path.write_text(arch_content, encoding="utf-8")
                logger.info("Generated ARCHITECTURE.md")

    def _generate_module_doc(self, module: Dict) -> str:
        # Get symbols for this module
        rows = self.db.conn.execute(
            """SELECT name, type, signature, doc_comment, start_line, file
               FROM symbols WHERE module_id = ? AND is_public = 1
               ORDER BY type, name LIMIT 40""",
            (module["id"],),
        ).fetchall()

        symbols_text = "\n".join(
            f"- [{r['type']}] {r['name']}"
            + (f": {r['signature']}" if r.get("signature") else "")
            + (f" — {r['doc_comment'][:80]}" if r.get("doc_comment") else "")
            for r in rows
        )

        # Get key relations
        rel_rows = self.db.conn.execute(
            """SELECT DISTINCT r.rel_type, s.name as src, r.target_name as tgt
               FROM relations r
               JOIN symbols s ON r.source_id = s.id
               WHERE s.module_id = ? AND r.rel_type IN ('EXTENDS','IMPLEMENTS','CONFORMS_TO','CALLS')
               LIMIT 20""",
            (module["id"],),
        ).fetchall()
        relations_text = "\n".join(
            f"- {r['src']} {r['rel_type']} {r['tgt']}" for r in rel_rows
        )

        prompt = MODULE_PROMPT.format(
            module_name=module["name"],
            files=", ".join(module["files"][:10]),
            symbols=symbols_text or "(no public symbols)",
            relations=relations_text or "(none detected)",
        )

        if not self.client:
            return self._fallback_module_doc(module, rows)

        try:
            message = self.client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1500,
                messages=[{"role": "user", "content": prompt}],
            )
            content = message.content[0].text
            self.db.upsert_module(
                module["id"], module["name"], module["files"],
                description=content[:200],
                summary=content[:200],
            )
            return f"# {module['name']}\n\n{content}"
        except Exception as e:
            logger.warning(f"Wiki generation failed for {module['name']}: {e}")
            return self._fallback_module_doc(module, rows)

    def _fallback_module_doc(self, module: Dict, rows) -> str:
        lines = [f"# {module['name']}\n"]
        lines.append(f"**Files**: {', '.join(module['files'][:5])}\n")
        if rows:
            lines.append("## Symbols\n")
            for r in rows:
                lines.append(f"- `{r['name']}` ({r['type']}) — {r['file']}:{r['start_line']}")
        return "\n".join(lines)

    def _generate_architecture(self, module_summaries: List[Dict]) -> str:
        modules_text = "\n\n".join(
            f"### {m['name']}\n{m['summary'][:300]}" for m in module_summaries
        )
        prompt = ARCH_PROMPT.format(
            repo_name=self.repo_root.name,
            modules=modules_text or "(no modules)",
        )
        if not self.client:
            lines = [f"# {self.repo_root.name} Architecture\n", "## Modules\n"]
            for m in module_summaries:
                lines.append(f"- **{m['name']}**")
            return "\n".join(lines)

        try:
            message = self.client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}],
            )
            return message.content[0].text
        except Exception as e:
            logger.warning(f"Architecture doc generation failed: {e}")
            lines = [f"# {self.repo_root.name} Architecture\n", "## Modules\n"]
            for m in module_summaries:
                lines.append(f"- **{m['name']}**")
            return "\n".join(lines)
