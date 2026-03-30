"""SQLite graph database for symbols and relations."""
import sqlite3
import json
import logging
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime

from reposage.indexer.models import Symbol, Relation

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS symbols (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    file TEXT NOT NULL,
    start_line INTEGER,
    end_line INTEGER,
    language TEXT,
    signature TEXT DEFAULT '',
    doc_comment TEXT DEFAULT '',
    is_public INTEGER DEFAULT 1,
    parent_name TEXT DEFAULT '',
    module_id TEXT DEFAULT '',
    summary TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS relations (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    target_id TEXT DEFAULT '',
    target_name TEXT NOT NULL,
    rel_type TEXT NOT NULL,
    confidence REAL DEFAULT 1.0,
    file TEXT DEFAULT '',
    line INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS modules (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    files TEXT DEFAULT '[]',
    summary TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS symbols_fts USING fts5(
    id UNINDEXED,
    name,
    signature,
    doc_comment,
    summary,
    content=symbols,
    content_rowid=rowid
);

CREATE TRIGGER IF NOT EXISTS symbols_ai AFTER INSERT ON symbols BEGIN
    INSERT INTO symbols_fts(rowid, id, name, signature, doc_comment, summary)
    VALUES (new.rowid, new.id, new.name, new.signature, new.doc_comment, new.summary);
END;

CREATE TRIGGER IF NOT EXISTS symbols_au AFTER UPDATE ON symbols BEGIN
    INSERT INTO symbols_fts(symbols_fts, rowid, id, name, signature, doc_comment, summary)
    VALUES ('delete', old.rowid, old.id, old.name, old.signature, old.doc_comment, old.summary);
    INSERT INTO symbols_fts(rowid, id, name, signature, doc_comment, summary)
    VALUES (new.rowid, new.id, new.name, new.signature, new.doc_comment, new.summary);
END;

CREATE TRIGGER IF NOT EXISTS symbols_ad AFTER DELETE ON symbols BEGIN
    INSERT INTO symbols_fts(symbols_fts, rowid, id, name, signature, doc_comment, summary)
    VALUES ('delete', old.rowid, old.id, old.name, old.signature, old.doc_comment, old.summary);
END;

CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);
CREATE INDEX IF NOT EXISTS idx_symbols_file ON symbols(file);
CREATE INDEX IF NOT EXISTS idx_symbols_type ON symbols(type);
CREATE INDEX IF NOT EXISTS idx_relations_source ON relations(source_id);
CREATE INDEX IF NOT EXISTS idx_relations_target ON relations(target_id);
CREATE INDEX IF NOT EXISTS idx_relations_target_name ON relations(target_name);
CREATE INDEX IF NOT EXISTS idx_relations_type ON relations(rel_type);

CREATE TABLE IF NOT EXISTS tool_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tool TEXT NOT NULL,
    query TEXT DEFAULT '',
    result_count INTEGER DEFAULT 0,
    ts TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evolution_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT NOT NULL,
    tool TEXT NOT NULL,
    was_helpful INTEGER NOT NULL,
    reason TEXT DEFAULT '',
    tip TEXT DEFAULT '',
    ts TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tool_calls_tool ON tool_calls(tool);
CREATE INDEX IF NOT EXISTS idx_tool_calls_ts ON tool_calls(ts);
CREATE INDEX IF NOT EXISTS idx_evolution_log_helpful ON evolution_log(was_helpful);
"""


class RepoSageDB:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self):
        self.conn.close()

    # ── Symbols ──────────────────────────────────────────────────────────────

    def upsert_symbols(self, symbols: List[Symbol]):
        rows = [
            (s.id, s.name, s.type, s.file, s.start_line, s.end_line,
             s.language, s.signature, s.doc_comment, int(s.is_public),
             s.parent_name, "", "")
            for s in symbols
        ]
        self.conn.executemany(
            """INSERT OR REPLACE INTO symbols
               (id, name, type, file, start_line, end_line, language,
                signature, doc_comment, is_public, parent_name, module_id, summary)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )
        self.conn.commit()

    def delete_symbols_for_file(self, file_rel: str):
        self.conn.execute("DELETE FROM symbols WHERE file = ?", (file_rel,))
        self.conn.execute("DELETE FROM relations WHERE file = ?", (file_rel,))
        self.conn.commit()

    def get_symbol(self, symbol_id: str) -> Optional[Dict]:
        row = self.conn.execute(
            "SELECT * FROM symbols WHERE id = ?", (symbol_id,)
        ).fetchone()
        return dict(row) if row else None

    def find_symbols_by_name(self, name: str) -> List[Dict]:
        rows = self.conn.execute(
            "SELECT * FROM symbols WHERE name = ? ORDER BY type, file", (name,)
        ).fetchall()
        return [dict(r) for r in rows]

    def search_symbols_fts(self, query: str, limit: int = 20) -> List[Dict]:
        try:
            rows = self.conn.execute(
                """SELECT s.*, rank FROM symbols s
                   JOIN symbols_fts f ON s.id = f.id
                   WHERE symbols_fts MATCH ?
                   ORDER BY rank LIMIT ?""",
                (query, limit),
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.warning(f"FTS search failed: {e}")
            # Fallback: LIKE search
            rows = self.conn.execute(
                "SELECT * FROM symbols WHERE name LIKE ? LIMIT ?",
                (f"%{query}%", limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_symbols_for_file(self, file_rel: str) -> List[Dict]:
        rows = self.conn.execute(
            "SELECT * FROM symbols WHERE file = ? ORDER BY start_line", (file_rel,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_all_symbols(self, language: Optional[str] = None) -> List[Dict]:
        if language:
            rows = self.conn.execute(
                "SELECT * FROM symbols WHERE language = ? ORDER BY file, start_line",
                (language,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM symbols ORDER BY file, start_line"
            ).fetchall()
        return [dict(r) for r in rows]

    def update_symbol_summary(self, symbol_id: str, summary: str):
        self.conn.execute(
            "UPDATE symbols SET summary = ? WHERE id = ?", (summary, symbol_id)
        )
        self.conn.commit()

    # ── Relations ─────────────────────────────────────────────────────────────

    def upsert_relations(self, relations: List[Relation]):
        rows = [
            (r.id, r.source_id, r.target_id, r.target_name,
             r.rel_type, r.confidence, r.file, r.line)
            for r in relations
        ]
        self.conn.executemany(
            """INSERT OR REPLACE INTO relations
               (id, source_id, target_id, target_name, rel_type, confidence, file, line)
               VALUES (?,?,?,?,?,?,?,?)""",
            rows,
        )
        self.conn.commit()

    def resolve_relations(self):
        """Fill target_id for unresolved relations using symbol name lookup."""
        unresolved = self.conn.execute(
            "SELECT id, target_name FROM relations WHERE target_id = '' AND target_name != ''"
        ).fetchall()

        updates = []
        for row in unresolved:
            matches = self.conn.execute(
                "SELECT id FROM symbols WHERE name = ? LIMIT 1", (row["target_name"],)
            ).fetchone()
            if matches:
                updates.append((matches["id"], row["id"]))

        if updates:
            self.conn.executemany(
                "UPDATE relations SET target_id = ? WHERE id = ?", updates
            )
            self.conn.commit()
        return len(updates)

    def get_callers(self, symbol_id: str, depth: int = 1) -> List[Dict]:
        """BFS upstream: who calls this symbol."""
        visited = set()
        result = []
        queue = [(symbol_id, 0)]
        while queue:
            sid, d = queue.pop(0)
            if d >= depth or sid in visited:
                continue
            visited.add(sid)
            rows = self.conn.execute(
                """SELECT r.*, s.name as source_name, s.file as source_file,
                          s.type as source_type, s.start_line as source_line
                   FROM relations r
                   JOIN symbols s ON r.source_id = s.id
                   WHERE r.target_id = ? AND r.rel_type = 'CALLS'""",
                (sid,),
            ).fetchall()
            for row in rows:
                entry = dict(row)
                entry["depth"] = d + 1
                result.append(entry)
                queue.append((row["source_id"], d + 1))
        return result

    def get_callees(self, symbol_id: str, depth: int = 1) -> List[Dict]:
        """BFS downstream: what does this symbol call."""
        visited = set()
        result = []
        queue = [(symbol_id, 0)]
        while queue:
            sid, d = queue.pop(0)
            if d >= depth or sid in visited:
                continue
            visited.add(sid)
            rows = self.conn.execute(
                """SELECT r.*, s.name as target_sym_name, s.file as target_file,
                          s.type as target_type, s.start_line as target_line
                   FROM relations r
                   LEFT JOIN symbols s ON r.target_id = s.id
                   WHERE r.source_id = ? AND r.rel_type = 'CALLS'""",
                (sid,),
            ).fetchall()
            for row in rows:
                entry = dict(row)
                entry["depth"] = d + 1
                result.append(entry)
                if row["target_id"]:
                    queue.append((row["target_id"], d + 1))
        return result

    def get_listeners_for_notification(self, notification_name: str) -> List[Dict]:
        """Find methods that registered to listen to a notification via LISTENS_TO relations."""
        rows = self.conn.execute(
            """SELECT r.source_id, r.line, r.file,
                      s.name, s.type, s.file as method_file,
                      s.start_line, s.parent_name, s.signature, s.summary
               FROM relations r
               JOIN symbols s ON r.source_id = s.id
               WHERE r.rel_type = 'LISTENS_TO'
                 AND (r.target_name = ? OR r.target_name LIKE ?)
               ORDER BY r.confidence DESC""",
            (notification_name, f"%{notification_name}%"),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_notifications_for_symbol(self, symbol_id: str) -> List[str]:
        """Return notification names that this symbol listens to."""
        rows = self.conn.execute(
            "SELECT target_name FROM relations WHERE source_id = ? AND rel_type = 'LISTENS_TO'",
            (symbol_id,),
        ).fetchall()
        return [r["target_name"] for r in rows]

    def get_relations_for_symbol(self, symbol_id: str) -> Dict[str, List[Dict]]:
        rows = self.conn.execute(
            "SELECT * FROM relations WHERE source_id = ? OR target_id = ?",
            (symbol_id, symbol_id),
        ).fetchall()
        incoming = []
        outgoing = []
        for row in rows:
            d = dict(row)
            if row["target_id"] == symbol_id:
                incoming.append(d)
            else:
                outgoing.append(d)
        return {"incoming": incoming, "outgoing": outgoing}

    # ── Modules ───────────────────────────────────────────────────────────────

    def upsert_module(self, module_id: str, name: str, files: List[str],
                      description: str = "", summary: str = ""):
        self.conn.execute(
            """INSERT OR REPLACE INTO modules (id, name, description, files, summary)
               VALUES (?,?,?,?,?)""",
            (module_id, name, description, json.dumps(files), summary),
        )
        # Update module_id on symbols
        for f in files:
            self.conn.execute(
                "UPDATE symbols SET module_id = ? WHERE file = ?", (module_id, f)
            )
        self.conn.commit()

    def get_all_modules(self) -> List[Dict]:
        rows = self.conn.execute("SELECT * FROM modules ORDER BY name").fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["files"] = json.loads(d["files"])
            result.append(d)
        return result

    def get_module(self, module_id: str) -> Optional[Dict]:
        row = self.conn.execute(
            "SELECT * FROM modules WHERE id = ?", (module_id,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["files"] = json.loads(d["files"])
        return d

    # ── Meta ──────────────────────────────────────────────────────────────────

    def set_meta(self, key: str, value: str):
        self.conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?,?)", (key, value)
        )
        self.conn.commit()

    def get_meta(self, key: str) -> Optional[str]:
        row = self.conn.execute(
            "SELECT value FROM meta WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None

    def get_stats(self) -> Dict[str, Any]:
        stats = {}
        stats["symbols"] = self.conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
        stats["relations"] = self.conn.execute("SELECT COUNT(*) FROM relations").fetchone()[0]
        stats["modules"] = self.conn.execute("SELECT COUNT(*) FROM modules").fetchone()[0]
        stats["files"] = self.conn.execute(
            "SELECT COUNT(DISTINCT file) FROM symbols"
        ).fetchone()[0]
        stats["last_indexed"] = self.get_meta("last_indexed") or "never"
        return stats

    def get_indexed_files(self) -> List[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT file FROM symbols ORDER BY file"
        ).fetchall()
        return [r["file"] for r in rows]

    # ── Evolution ─────────────────────────────────────────────────────────────

    def log_tool_call(self, tool: str, query: str, result_count: int):
        from datetime import datetime, timezone
        self.conn.execute(
            "INSERT INTO tool_calls (tool, query, result_count, ts) VALUES (?, ?, ?, ?)",
            (tool, query, result_count, datetime.now(timezone.utc).isoformat()),
        )
        self.conn.commit()

    def log_feedback(self, query: str, tool: str, was_helpful: bool,
                     reason: str = "", tip: str = ""):
        from datetime import datetime, timezone
        self.conn.execute(
            "INSERT INTO evolution_log (query, tool, was_helpful, reason, tip, ts) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (query, tool, int(was_helpful), reason, tip,
             datetime.now(timezone.utc).isoformat()),
        )
        self.conn.commit()

    def get_failure_tips(self, limit: int = 10) -> List[Dict]:
        """Return recent non-empty tips from failed interactions."""
        rows = self.conn.execute(
            """SELECT tip, query, tool FROM evolution_log
               WHERE was_helpful = 0 AND tip != ''
               ORDER BY id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_tool_stats(self) -> List[Dict]:
        """Return per-tool call count and avg result_count."""
        rows = self.conn.execute(
            """SELECT tool,
                      COUNT(*) as calls,
                      ROUND(AVG(result_count), 1) as avg_results,
                      SUM(CASE WHEN result_count = 0 THEN 1 ELSE 0 END) as zero_result_calls
               FROM tool_calls
               GROUP BY tool
               ORDER BY calls DESC"""
        ).fetchall()
        return [dict(r) for r in rows]

    def get_evolution_summary(self) -> Dict[str, Any]:
        """Return overall evolution stats."""
        total = self.conn.execute("SELECT COUNT(*) FROM evolution_log").fetchone()[0]
        helpful = self.conn.execute(
            "SELECT COUNT(*) FROM evolution_log WHERE was_helpful = 1"
        ).fetchone()[0]
        tips_count = self.conn.execute(
            "SELECT COUNT(*) FROM evolution_log WHERE tip != ''"
        ).fetchone()[0]
        return {
            "total_feedback": total,
            "helpful": helpful,
            "not_helpful": total - helpful,
            "tips_accumulated": tips_count,
        }
