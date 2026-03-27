"""Generate the Agent compression layer: .reposage/*.json/yaml files."""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import yaml

from reposage.storage.db import RepoSageDB

logger = logging.getLogger(__name__)


class AgentIndexGenerator:
    def __init__(self, repo_root: Path, db: RepoSageDB):
        self.repo_root = repo_root
        self.db = db
        self.out_dir = repo_root / ".reposage"
        self.out_dir.mkdir(exist_ok=True)

    def generate(self):
        self._write_symbols()
        self._write_relations()
        self._write_modules()
        self._write_index()

    # ── symbols.json ─────────────────────────────────────────────────────────

    def _write_symbols(self):
        symbols = self.db.get_all_symbols()
        # Slim down to essential fields only
        slim = []
        for s in symbols:
            slim.append({
                "id": s["id"],
                "name": s["name"],
                "type": s["type"],
                "file": s["file"],
                "line": s["start_line"],
                "lang": s["language"],
                "sig": s.get("signature") or "",
                "doc": (s.get("doc_comment") or "")[:120],
                "parent": s.get("parent_name") or "",
                "module": s.get("module_id") or "",
                "summary": (s.get("summary") or "")[:200],
            })
        self._write_json("symbols.json", slim)
        logger.info(f"Wrote {len(slim)} symbols")

    # ── relations.json ───────────────────────────────────────────────────────

    def _write_relations(self):
        rows = self.db.conn.execute(
            """SELECT source_id, target_id, target_name, rel_type, confidence, file, line
               FROM relations ORDER BY source_id, rel_type"""
        ).fetchall()
        relations = []
        for r in rows:
            relations.append({
                "src": r["source_id"],
                "tgt": r["target_id"] or "",
                "tgt_name": r["target_name"],
                "type": r["rel_type"],
                "conf": round(r["confidence"], 2),
                "file": r["file"],
                "line": r["line"],
            })
        self._write_json("relations.json", relations)
        logger.info(f"Wrote {len(relations)} relations")

    # ── modules.yaml ─────────────────────────────────────────────────────────

    def _write_modules(self):
        modules = self.db.get_all_modules()
        output = []
        for m in modules:
            # Collect top exported symbols (public classes/protocols/functions)
            rows = self.db.conn.execute(
                """SELECT name, type FROM symbols
                   WHERE module_id = ? AND is_public = 1
                     AND type IN ('class','interface','protocol','function','enum')
                   ORDER BY type, name LIMIT 30""",
                (m["id"],),
            ).fetchall()
            exported = [f"{r['name']} ({r['type']})" for r in rows]
            output.append({
                "id": m["id"],
                "name": m["name"],
                "files": m["files"],
                "description": m.get("description") or "",
                "summary": m.get("summary") or "",
                "exported": exported,
            })
        with open(self.out_dir / "modules.yaml", "w") as f:
            yaml.dump({"modules": output}, f, allow_unicode=True, sort_keys=False)
        logger.info(f"Wrote {len(output)} modules")

    # ── index.json ───────────────────────────────────────────────────────────

    def _write_index(self):
        stats = self.db.get_stats()

        # Build name → [id] lookup
        rows = self.db.conn.execute(
            "SELECT name, id FROM symbols ORDER BY name"
        ).fetchall()
        symbol_index: Dict[str, List[str]] = {}
        for r in rows:
            symbol_index.setdefault(r["name"], []).append(r["id"])

        # File → symbol ids
        file_rows = self.db.conn.execute(
            "SELECT file, id FROM symbols ORDER BY file, start_line"
        ).fetchall()
        file_index: Dict[str, List[str]] = {}
        for r in file_rows:
            file_index.setdefault(r["file"], []).append(r["id"])

        index = {
            "version": "1.0",
            "repo": self.repo_root.name,
            "generated": datetime.now().isoformat(),
            "stats": stats,
            "symbol_index": symbol_index,
            "file_index": file_index,
            "usage": {
                "mcp": f"claude mcp add reposage -- python -m reposage mcp --repo {self.repo_root}",
                "files": {
                    "symbols": ".reposage/symbols.json",
                    "relations": ".reposage/relations.json",
                    "modules": ".reposage/modules.yaml",
                },
            },
        }
        self._write_json("index.json", index)

    def _write_json(self, filename: str, data):
        path = self.out_dir / filename
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
