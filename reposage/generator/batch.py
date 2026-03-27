"""Batch LLM generation for summaries and wiki — runs autonomously without MCP."""
import json
import logging
import os
from pathlib import Path
from typing import List, Dict

import anthropic

logger = logging.getLogger(__name__)

SUMMARY_BATCH_SIZE = 50

SUMMARY_SYSTEM = (
    "You are a code documentation assistant. "
    "For each symbol provided, write a single concise sentence (in Chinese or English, "
    "matching the codebase language) describing what it does. "
    "Return ONLY a JSON array: [{\"id\": \"<id>\", \"summary\": \"<one sentence>\"}, ...]"
)

SUMMARY_USER_TMPL = """\
Generate one-sentence summaries for the following {n} symbols.

{items}

Return ONLY a JSON array with {n} objects, each having "id" and "summary" fields.
"""

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


class BatchGenerator:
    def __init__(self, repo_root: Path, db, vector_store, model: str = "claude-haiku-4-5-20251001"):
        self.repo_root = repo_root
        self.db = db
        self.vector_store = vector_store
        self.model = model

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY environment variable not set.")
        self.client = anthropic.Anthropic(api_key=api_key)

        from reposage.indexer.pipeline import get_reposage_dir
        self.reposage_dir = get_reposage_dir(repo_root)
        self.docs_dir = self.reposage_dir / "docs"
        self.modules_dir = self.docs_dir / "modules"
        self.docs_dir.mkdir(parents=True, exist_ok=True)
        self.modules_dir.mkdir(exist_ok=True)

    # ------------------------------------------------------------------ #
    # Summaries                                                            #
    # ------------------------------------------------------------------ #

    def generate_summaries(self, language: str = None, console=None) -> int:
        """Batch-generate summaries for all symbols missing one. Returns total written."""
        total_written = 0

        while True:
            batch = self._fetch_pending_symbols(language, SUMMARY_BATCH_SIZE)
            if not batch:
                break

            remaining_before = self._count_pending(language)
            if console:
                console.print(
                    f"  [dim]Generating summaries for {len(batch)} symbols "
                    f"({remaining_before} remaining)…[/dim]"
                )

            summaries = self._call_summary_api(batch)
            written = self._write_summaries(summaries)
            total_written += written

            if console:
                console.print(f"  [green]✓[/green] Wrote {written} summaries")

            remaining_after = self._count_pending(language)
            if remaining_after == 0:
                break
            if written == 0:
                raise RuntimeError(
                    f"No summaries written in this batch — aborting to avoid infinite loop. "
                    f"Still pending: {remaining_after}"
                )

        return total_written

    def _fetch_pending_symbols(self, language: str, limit: int) -> List[Dict]:
        if language:
            rows = self.db.conn.execute(
                """SELECT id, name, type, signature, parent_name, doc_comment, file, start_line, language
                   FROM symbols
                   WHERE (summary IS NULL OR summary = '') AND language = ?
                   ORDER BY type, file, start_line LIMIT ?""",
                (language, limit),
            ).fetchall()
        else:
            rows = self.db.conn.execute(
                """SELECT id, name, type, signature, parent_name, doc_comment, file, start_line, language
                   FROM symbols
                   WHERE summary IS NULL OR summary = ''
                   ORDER BY type, file, start_line LIMIT ?""",
                (limit,),
            ).fetchall()

        batch = []
        for r in rows:
            callee_rows = self.db.conn.execute(
                """SELECT DISTINCT r.target_name FROM relations r
                   WHERE r.source_id = ? AND r.rel_type = 'CALLS' LIMIT 5""",
                (r["id"],),
            ).fetchall()
            batch.append({
                "id": r["id"],
                "name": r["name"],
                "type": r["type"],
                "language": r["language"],
                "signature": r["signature"] or "",
                "parent_name": r["parent_name"] or "",
                "doc_comment": (r["doc_comment"] or "")[:200],
                "file": r["file"],
                "line": r["start_line"],
                "callee_names": [c["target_name"] for c in callee_rows],
            })
        return batch

    def _count_pending(self, language: str = None) -> int:
        if language:
            return self.db.conn.execute(
                "SELECT COUNT(*) FROM symbols WHERE (summary IS NULL OR summary = '') AND language = ?",
                (language,),
            ).fetchone()[0]
        return self.db.conn.execute(
            "SELECT COUNT(*) FROM symbols WHERE summary IS NULL OR summary = ''"
        ).fetchone()[0]

    def _call_summary_api(self, batch: List[Dict]) -> List[Dict]:
        items_text = "\n".join(
            f"{i+1}. id={s['id']} name={s['name']} type={s['type']}"
            + (f" parent={s['parent_name']}" if s["parent_name"] else "")
            + (f" signature={s['signature'][:80]}" if s["signature"] else "")
            + (f" calls=[{', '.join(s['callee_names'][:3])}]" if s["callee_names"] else "")
            + (f" doc={s['doc_comment'][:60]}" if s["doc_comment"] else "")
            for i, s in enumerate(batch)
        )
        prompt = SUMMARY_USER_TMPL.format(n=len(batch), items=items_text)

        message = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=SUMMARY_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()

        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.rsplit("```", 1)[0].strip()

        try:
            result = json.loads(raw)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"API returned invalid JSON for summaries: {e}\nRaw: {raw[:500]}")

        if not isinstance(result, list):
            raise RuntimeError(f"Expected JSON array from API, got: {type(result)}")

        return result

    def _write_summaries(self, summaries: List[Dict]) -> int:
        written = 0
        ids_written = []
        for item in summaries:
            sid = item.get("id")
            summary = (item.get("summary") or "").strip()
            if sid and summary:
                self.db.conn.execute(
                    "UPDATE symbols SET summary = ? WHERE id = ?", (summary, sid)
                )
                written += 1
                ids_written.append(sid)
        self.db.conn.commit()

        # Re-embed updated symbols
        if ids_written:
            updated = [self.db.get_symbol(sid) for sid in ids_written]
            updated = [s for s in updated if s]
            if updated:
                self.vector_store.upsert_symbols(updated)

        return written

    # ------------------------------------------------------------------ #
    # Wiki                                                                 #
    # ------------------------------------------------------------------ #

    def generate_wiki(self, force: bool = False, console=None) -> int:
        """Generate wiki docs for all modules. Returns number of modules written."""
        modules = self.db.get_all_modules()
        module_summaries = []
        written = 0

        for module in modules:
            md_path = self.modules_dir / f"{module['name']}.md"
            if md_path.exists() and not force:
                existing = md_path.read_text(encoding="utf-8")
                module_summaries.append({"name": module["name"], "summary": existing[:500]})
                continue

            if console:
                console.print(f"  [dim]Generating wiki for module: {module['name']}…[/dim]")

            content = self._generate_module_doc(module)
            md_path.write_text(f"# {module['name']}\n\n{content}", encoding="utf-8")
            self.db.upsert_module(
                module["id"], module["name"], module["files"],
                description=content[:200],
                summary=content[:200],
            )
            module_summaries.append({"name": module["name"], "summary": content[:500]})
            written += 1
            if console:
                console.print(f"  [green]✓[/green] {module['name']}")

        arch_path = self.docs_dir / "ARCHITECTURE.md"
        if not arch_path.exists() or force:
            if console:
                console.print("  [dim]Generating ARCHITECTURE.md…[/dim]")
            arch_content = self._generate_architecture(module_summaries)
            arch_path.write_text(arch_content, encoding="utf-8")
            if console:
                console.print("  [green]✓[/green] ARCHITECTURE.md")

        return written

    def _generate_module_doc(self, module: Dict) -> str:
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
        message = self.client.messages.create(
            model=self.model,
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text

    def _generate_architecture(self, module_summaries: List[Dict]) -> str:
        modules_text = "\n\n".join(
            f"### {m['name']}\n{m['summary'][:300]}" for m in module_summaries
        )
        prompt = ARCH_PROMPT.format(
            repo_name=self.repo_root.name,
            modules=modules_text or "(no modules)",
        )
        message = self.client.messages.create(
            model=self.model,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text
