"""MCP Server — exposes RepoSage knowledge graph to AI agents."""
import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


async def start_mcp_server(repos: dict):
    """Entry point: start the MCP stdio server for one or more repos.

    Args:
        repos: dict mapping repo_name -> repo_root Path
    """
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp import types

    from reposage.storage.db import RepoSageDB
    from reposage.storage.vector_store import VectorStore
    from reposage.indexer.pipeline import get_reposage_dir

    # Build registry: name -> {db, vector_store, root}
    repos_registry: dict = {}
    for name, repo_root in repos.items():
        reposage_dir = get_reposage_dir(repo_root)
        db_path = reposage_dir / "index.db"
        if not db_path.exists():
            logger.warning(f"Repo '{name}' not indexed, skipping. Run: reposage analyze {repo_root}")
            continue
        repos_registry[name] = {
            "db": RepoSageDB(db_path),
            "vector_store": VectorStore(reposage_dir / "vectors", name),
            "root": repo_root,
        }

    if not repos_registry:
        raise FileNotFoundError("No indexed repositories found. Run: reposage analyze <repo_path>")

    # Backwards-compat: keep single-repo shortcuts
    _single = list(repos_registry.values())[0] if len(repos_registry) == 1 else None

    server = Server("reposage")

    # ── Tool Handlers ─────────────────────────────────────────────────────────

    repo_param = {
        "repo": {
            "type": "string",
            "description": (
                f"Repository name to query. Available: {', '.join(repos_registry.keys())}. "
                "Omit if only one repo is loaded."
            ),
        }
    }

    @server.list_tools()
    async def list_tools():
        return [
            types.Tool(
                name="list_repos",
                description="List all loaded repositories with their index stats.",
                inputSchema={"type": "object", "properties": {}},
            ),
            types.Tool(
                name="search",
                description=(
                    "Hybrid search (full-text + semantic) across all symbols. "
                    "Returns matching classes, methods, functions with file locations."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "limit": {"type": "integer", "default": 15},
                        "language": {
                            "type": "string",
                            "description": "Filter by language: objc, swift, java",
                        },
                        **repo_param,
                    },
                    "required": ["query"],
                },
            ),
            types.Tool(
                name="symbol_context",
                description=(
                    "360° view of a symbol: callers, callees, parent class, module, "
                    "file location, doc comment. Use after search() to drill into a result."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Symbol name"},
                        "id": {"type": "string", "description": "Symbol ID (exact, from search results)"},
                        "file": {"type": "string", "description": "File path to disambiguate"},
                        **repo_param,
                    },
                },
            ),
            types.Tool(
                name="find_callers",
                description="Find all code locations that call a given method or function.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Method/function name"},
                        "depth": {"type": "integer", "default": 2, "description": "BFS depth"},
                        **repo_param,
                    },
                    "required": ["name"],
                },
            ),
            types.Tool(
                name="impact",
                description=(
                    "Blast-radius analysis: what would break if this symbol changes? "
                    "Use before editing a class or method."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "target": {"type": "string", "description": "Symbol name or ID"},
                        "direction": {
                            "type": "string",
                            "enum": ["upstream", "downstream", "both"],
                            "default": "upstream",
                        },
                        "depth": {"type": "integer", "default": 3},
                        **repo_param,
                    },
                    "required": ["target"],
                },
            ),
            types.Tool(
                name="module_overview",
                description="Get a module's files, exported symbols, and description.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Module name (directory name)"},
                        **repo_param,
                    },
                    "required": ["name"],
                },
            ),
            types.Tool(
                name="execution_flow",
                description=(
                    "Trace execution from an entry point: follow CALLS edges BFS. "
                    "Useful for understanding 'how does X work end to end'."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "entry_point": {"type": "string", "description": "Starting method/function name"},
                        "depth": {"type": "integer", "default": 5},
                        **repo_param,
                    },
                    "required": ["entry_point"],
                },
            ),
            types.Tool(
                name="ask",
                description=(
                    "RAG-powered Q&A about the codebase. "
                    "Retrieves relevant symbols and docs as context — YOU (the LLM) answer the question."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        **repo_param,
                    },
                    "required": ["question"],
                },
            ),
            types.Tool(
                name="get_pending_summaries",
                description=(
                    "Return a batch of symbols that have no summary yet, with enough context "
                    "(signature, parent class, callees, doc comment) for YOU to generate a one-sentence summary. "
                    "After generating summaries, call write_summaries to persist them."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "batch_size": {
                            "type": "integer",
                            "default": 50,
                            "description": "Number of symbols to return per batch (max 200)",
                        },
                        "language": {
                            "type": "string",
                            "description": "Filter by language: objc, swift, java",
                        },
                        **repo_param,
                    },
                },
            ),
            types.Tool(
                name="write_summaries",
                description=(
                    "Persist summaries you generated into the DB and update vector embeddings. "
                    "Call this after get_pending_summaries + generating summaries."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "summaries": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "summary": {"type": "string"},
                                },
                                "required": ["id", "summary"],
                            },
                            "description": "List of {id, summary} pairs",
                        },
                        **repo_param,
                    },
                    "required": ["summaries"],
                },
            ),
            types.Tool(
                name="get_pending_wiki",
                description=(
                    "Return modules that have no wiki doc yet, with full context (symbols + relations) "
                    "for YOU to generate Markdown documentation. "
                    "After generating, call write_wiki to persist."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {**repo_param},
                },
            ),
            types.Tool(
                name="write_wiki",
                description=(
                    "Persist wiki Markdown docs you generated into docs/ directory and update module DB entries."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "modules": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "name": {"type": "string"},
                                    "content": {"type": "string"},
                                },
                                "required": ["id", "name", "content"],
                            },
                            "description": "List of {id, name, content} module wiki docs",
                        },
                        "architecture": {
                            "type": "string",
                            "description": "Content for ARCHITECTURE.md (optional)",
                        },
                        **repo_param,
                    },
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
        try:
            result = await _dispatch(name, arguments, repos_registry)
            return [types.TextContent(type="text", text=result)]
        except Exception as e:
            logger.exception(f"Tool {name} failed")
            return [types.TextContent(type="text", text=f"Error: {e}")]

    # ── Resource Handlers ─────────────────────────────────────────────────────

    @server.list_resources()
    async def list_resources():
        resources = []
        for rname in repos_registry:
            resources.append(types.Resource(
                uri=f"reposage://{rname}/context",
                name=f"{rname} — Repository Context",
                description=f"Stats, index status, module list for {rname}",
                mimeType="application/json",
            ))
            resources.append(types.Resource(
                uri=f"reposage://{rname}/modules",
                name=f"{rname} — All Modules",
                description=f"Module topology with exported symbols for {rname}",
                mimeType="application/json",
            ))
        return resources

    @server.read_resource()
    async def read_resource(uri: str) -> str:
        # uri format: reposage://{repo_name}/context or reposage://{repo_name}/modules
        parts = uri.replace("reposage://", "").split("/", 1)
        if len(parts) != 2:
            return json.dumps({"error": f"Unknown resource: {uri}"})
        rname, resource_type = parts
        entry = repos_registry.get(rname)
        if not entry:
            return json.dumps({"error": f"Repo '{rname}' not found"})
        db = entry["db"]
        root = entry["root"]
        if resource_type == "context":
            stats = db.get_stats()
            modules = [m["name"] for m in db.get_all_modules()]
            return json.dumps({"repo": rname, "stats": stats, "modules": modules}, indent=2)
        elif resource_type == "modules":
            modules = db.get_all_modules()
            return json.dumps(modules, indent=2, ensure_ascii=False)
        return json.dumps({"error": f"Unknown resource type: {resource_type}"})

    # ── Start ─────────────────────────────────────────────────────────────────

    async with stdio_server() as (read_stream, write_stream):
        from mcp.server.models import InitializationOptions
        from mcp.server import NotificationOptions
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="reposage",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


# ── Tool implementations ───────────────────────────────────────────────────────

def _resolve_repo(args: dict, repos_registry: dict):
    """Return (db, vector_store, root) for the requested repo, or an error string."""
    repo_name = args.get("repo")
    if repo_name:
        entry = repos_registry.get(repo_name)
        if not entry:
            available = ", ".join(repos_registry.keys())
            return None, f"Repo '{repo_name}' not found. Available: {available}"
        return entry, None
    # No repo specified
    if len(repos_registry) == 1:
        return list(repos_registry.values())[0], None
    available = ", ".join(repos_registry.keys())
    return None, (
        f"Multiple repos loaded: {available}. "
        f"Please specify repo=<name> in your tool call."
    )


async def _dispatch(name: str, args: dict, repos_registry: dict) -> str:
    if name == "list_repos":
        return _tool_list_repos(repos_registry)

    entry, err = _resolve_repo(args, repos_registry)
    if err:
        return err
    db = entry["db"]
    vector_store = entry["vector_store"]
    repo_root = entry["root"]

    if name == "search":
        return _tool_search(args, db, vector_store)
    elif name == "symbol_context":
        return _tool_symbol_context(args, db)
    elif name == "find_callers":
        return _tool_find_callers(args, db)
    elif name == "impact":
        return _tool_impact(args, db)
    elif name == "module_overview":
        return _tool_module_overview(args, db)
    elif name == "execution_flow":
        return _tool_execution_flow(args, db)
    elif name == "ask":
        return _tool_ask(args, db, vector_store, repo_root)
    elif name == "get_pending_summaries":
        return _tool_get_pending_summaries(args, db)
    elif name == "write_summaries":
        return _tool_write_summaries(args, db, vector_store)
    elif name == "get_pending_wiki":
        return _tool_get_pending_wiki(args, db, repo_root)
    elif name == "write_wiki":
        return _tool_write_wiki(args, db, repo_root)
    return f"Unknown tool: {name}"


def _tool_list_repos(repos_registry: dict) -> str:
    lines = [f"## Loaded Repositories ({len(repos_registry)})\n"]
    for name, entry in repos_registry.items():
        stats = entry["db"].get_stats()
        lines.append(
            f"### {name}\n"
            f"  Path: {entry['root']}\n"
            f"  Symbols: {stats['symbols']}  Relations: {stats['relations']}  "
            f"Modules: {stats['modules']}  Files: {stats['files']}\n"
            f"  Last indexed: {stats.get('last_indexed', 'unknown')}"
        )
    return "\n".join(lines)


def _tool_search(args: dict, db, vector_store) -> str:
    query = args["query"]
    limit = args.get("limit", 15)
    language = args.get("language")

    # FTS search
    fts_results = db.search_symbols_fts(query, limit=limit)

    # Semantic search
    sem_results = vector_store.search(query, limit=limit, language=language)
    sem_ids = {r["id"] for r in sem_results}

    # Merge: FTS first, then semantic-only additions
    seen = set()
    merged = []
    for r in fts_results:
        if language and r.get("language") != language:
            continue
        seen.add(r["id"])
        merged.append(r)

    for r in sem_results:
        if r["id"] not in seen:
            # Fetch full symbol from DB
            sym = db.get_symbol(r["id"])
            if sym:
                sym["semantic_score"] = r["score"]
                merged.append(sym)

    merged = merged[:limit]
    if not merged:
        return "No results found."

    lines = [f"Found {len(merged)} results for '{query}':\n"]
    for s in merged:
        sig = f" — {s['signature']}" if s.get("signature") else ""
        doc = f"\n    {s['doc_comment'][:80]}" if s.get("doc_comment") else ""
        lines.append(
            f"• [{s['type']}] **{s['name']}**{sig}\n"
            f"  {s['file']}:{s['start_line']}  (id: {s['id']}){doc}"
        )

    lines.append(
        "\n---\nNext: use symbol_context(id='<id>') for a 360° view of any result."
    )
    return "\n".join(lines)


def _tool_symbol_context(args: dict, db) -> str:
    sym_id = args.get("id")
    name = args.get("name")
    file_hint = args.get("file")

    sym = None
    if sym_id:
        sym = db.get_symbol(sym_id)
    elif name:
        candidates = db.find_symbols_by_name(name)
        if file_hint:
            candidates = [c for c in candidates if file_hint in c["file"]] or candidates
        if len(candidates) == 1:
            sym = candidates[0]
        elif len(candidates) > 1:
            lines = [f"Ambiguous: {len(candidates)} symbols named '{name}'. Specify id=:\n"]
            for c in candidates[:8]:
                lines.append(f"  id={c['id']}  {c['file']}:{c['start_line']}  ({c['type']})")
            return "\n".join(lines)

    if not sym:
        return f"Symbol not found: {name or sym_id}"

    relations = db.get_relations_for_symbol(sym["id"])
    callers = db.get_callers(sym["id"], depth=2)
    callees = db.get_callees(sym["id"], depth=2)

    lines = [
        f"## {sym['name']} ({sym['type']})",
        f"**File**: {sym['file']}:{sym['start_line']}",
        f"**Language**: {sym['language']}",
    ]
    if sym.get("signature"):
        lines.append(f"**Signature**: `{sym['signature']}`")
    if sym.get("parent_name"):
        lines.append(f"**Parent**: {sym['parent_name']}")
    if sym.get("doc_comment"):
        lines.append(f"**Doc**: {sym['doc_comment'][:200]}")
    if sym.get("summary"):
        lines.append(f"**Summary**: {sym['summary']}")

    if callers:
        lines.append(f"\n### Callers ({len(callers)})")
        for c in callers[:10]:
            lines.append(f"  • {c['source_name']} ({c['source_type']}) — {c['source_file']}:{c['source_line']}")

    if callees:
        lines.append(f"\n### Calls ({len(callees)})")
        for c in callees[:10]:
            tgt = c.get("target_sym_name") or c.get("target_name", "?")
            lines.append(f"  • {tgt} — {c.get('target_file', '?')}:{c.get('target_line', '?')}")

    # Inheritance
    for r in relations["outgoing"]:
        if r["rel_type"] in ("EXTENDS", "IMPLEMENTS", "CONFORMS_TO"):
            lines.append(f"\n**{r['rel_type']}**: {r['target_name']}")

    lines.append(f"\n---\nNext: impact(target='{sym['name']}', direction='upstream') to see blast radius.")
    return "\n".join(lines)


def _tool_find_callers(args: dict, db) -> str:
    name = args["name"]
    depth = min(args.get("depth", 2), 5)

    candidates = db.find_symbols_by_name(name)
    if not candidates:
        return f"No symbol named '{name}' found."

    all_callers = []
    for sym in candidates[:3]:
        callers = db.get_callers(sym["id"], depth=depth)
        all_callers.extend(callers)

    if not all_callers:
        return f"No callers found for '{name}'."

    # Deduplicate
    seen = set()
    unique = []
    for c in all_callers:
        key = (c["source_id"], c["depth"])
        if key not in seen:
            seen.add(key)
            unique.append(c)

    lines = [f"## Callers of `{name}` ({len(unique)} found)\n"]
    for c in sorted(unique, key=lambda x: x["depth"]):
        indent = "  " * c["depth"]
        lines.append(
            f"{indent}• **{c['source_name']}** ({c['source_type']}) "
            f"— {c['source_file']}:{c['source_line']}  [depth {c['depth']}]"
        )
    return "\n".join(lines)


def _tool_impact(args: dict, db) -> str:
    target = args["target"]
    direction = args.get("direction", "upstream")
    depth = min(args.get("depth", 3), 5)

    # Resolve symbol
    candidates = db.find_symbols_by_name(target)
    if not candidates:
        sym = db.get_symbol(target)
        if sym:
            candidates = [sym]
    if not candidates:
        return f"Symbol '{target}' not found."

    sym = candidates[0]
    lines = [f"## Impact Analysis: `{sym['name']}` ({sym['type']})\n"]
    lines.append(f"**File**: {sym['file']}:{sym['start_line']}\n")

    if direction in ("upstream", "both"):
        callers = db.get_callers(sym["id"], depth=depth)
        if callers:
            lines.append(f"### Upstream — {len(callers)} symbols depend on this\n")
            by_depth: dict = {}
            for c in callers:
                by_depth.setdefault(c["depth"], []).append(c)
            for d in sorted(by_depth):
                label = {1: "WILL BREAK", 2: "LIKELY AFFECTED", 3: "MAY NEED TESTING"}.get(d, f"depth {d}")
                lines.append(f"**Depth {d} — {label}**")
                for c in by_depth[d][:8]:
                    lines.append(f"  • {c['source_name']} ({c['source_type']}) — {c['source_file']}:{c['source_line']}")
        else:
            lines.append("### Upstream — no callers found (safe to change)\n")

    if direction in ("downstream", "both"):
        callees = db.get_callees(sym["id"], depth=depth)
        if callees:
            lines.append(f"\n### Downstream — this calls {len(callees)} symbols\n")
            for c in callees[:10]:
                tgt = c.get("target_sym_name") or c.get("target_name", "?")
                lines.append(f"  • {tgt} — {c.get('target_file', '?')}")

    return "\n".join(lines)


def _tool_module_overview(args: dict, db) -> str:
    name = args["name"]
    modules = db.get_all_modules()
    module = next((m for m in modules if m["name"].lower() == name.lower()), None)
    if not module:
        # Fuzzy match
        module = next((m for m in modules if name.lower() in m["name"].lower()), None)
    if not module:
        names = [m["name"] for m in modules]
        return f"Module '{name}' not found. Available modules:\n" + "\n".join(f"  • {n}" for n in names)

    rows = db.conn.execute(
        """SELECT name, type, file, start_line FROM symbols
           WHERE module_id = ? AND is_public = 1
           ORDER BY type, name LIMIT 50""",
        (module["id"],),
    ).fetchall()

    lines = [
        f"## Module: {module['name']}",
        f"**Files** ({len(module['files'])}): {', '.join(module['files'][:5])}{'...' if len(module['files']) > 5 else ''}",
    ]
    if module.get("description"):
        lines.append(f"**Description**: {module['description']}")
    if module.get("summary"):
        lines.append(f"**Summary**: {module['summary']}")

    if rows:
        lines.append(f"\n### Exported Symbols ({len(rows)})")
        by_type: dict = {}
        for r in rows:
            by_type.setdefault(r["type"], []).append(r)
        for t, syms in sorted(by_type.items()):
            lines.append(f"\n**{t.capitalize()}s**")
            for s in syms[:10]:
                lines.append(f"  • {s['name']} — {s['file']}:{s['start_line']}")

    return "\n".join(lines)


def _tool_execution_flow(args: dict, db) -> str:
    entry = args["entry_point"]
    max_depth = min(args.get("depth", 5), 8)

    candidates = db.find_symbols_by_name(entry)
    if not candidates:
        return f"Entry point '{entry}' not found."

    sym = candidates[0]
    visited = set()
    steps = []

    def bfs(sid: str, depth: int):
        if depth > max_depth or sid in visited:
            return
        visited.add(sid)
        s = db.get_symbol(sid)
        if s:
            steps.append((depth, s))
        callees = db.get_callees(sid, depth=1)
        for c in callees[:4]:  # limit branching
            if c.get("target_id"):
                bfs(c["target_id"], depth + 1)

    bfs(sym["id"], 0)

    if not steps:
        return f"No execution flow found from '{entry}'."

    lines = [f"## Execution Flow from `{entry}`\n"]
    for depth, s in steps:
        indent = "  " * depth
        arrow = "→ " if depth > 0 else ""
        lines.append(f"{indent}{arrow}**{s['name']}** ({s['type']}) — {s['file']}:{s['start_line']}")

    return "\n".join(lines)


def _tool_ask(args: dict, db, vector_store, repo_root: Path) -> str:
    """Return retrieved context for the question. The calling LLM answers it."""
    question = args["question"]

    fts = db.search_symbols_fts(question, limit=10)
    sem = vector_store.search(question, limit=10)

    context_parts = []
    seen = set()

    for s in fts + sem:
        sid = s.get("id")
        if sid and sid not in seen:
            seen.add(sid)
            # Fetch full symbol so we have summary too
            full = db.get_symbol(sid) or s
            sig = full.get("signature") or ""
            doc = full.get("doc_comment") or ""
            summary = full.get("summary") or ""
            context_parts.append(
                f"[{full.get('type','?')}] {full.get('name','?')} "
                f"in {full.get('file','?')}:{full.get('start_line','?')}"
                + (f"\n  Signature: {sig}" if sig else "")
                + (f"\n  Summary: {summary[:200]}" if summary else "")
                + (f"\n  Doc: {doc[:150]}" if doc else "")
            )

    from reposage.indexer.pipeline import get_reposage_dir
    arch_md = get_reposage_dir(repo_root) / "docs" / "ARCHITECTURE.md"
    wiki_context = ""
    if arch_md.exists():
        wiki_context = arch_md.read_text(encoding="utf-8")[:2000]

    context = "\n\n".join(context_parts[:15])
    if wiki_context:
        context = f"## Architecture Overview\n{wiki_context}\n\n## Relevant Symbols\n{context}"

    return (
        f"## Question\n{question}\n\n"
        f"## Retrieved Context\n{context}\n\n"
        f"---\nAnswer the question above using the retrieved context."
    )


def _tool_get_pending_summaries(args: dict, db) -> str:
    batch_size = min(int(args.get("batch_size", 50)), 200)
    language = args.get("language")

    # Count total pending
    if language:
        total = db.conn.execute(
            "SELECT COUNT(*) FROM symbols WHERE (summary IS NULL OR summary = '') AND language = ?",
            (language,),
        ).fetchone()[0]
        rows = db.conn.execute(
            """SELECT id, name, type, signature, parent_name, doc_comment, file, start_line, language
               FROM symbols
               WHERE (summary IS NULL OR summary = '') AND language = ?
               ORDER BY type, file, start_line
               LIMIT ?""",
            (language, batch_size),
        ).fetchall()
    else:
        total = db.conn.execute(
            "SELECT COUNT(*) FROM symbols WHERE summary IS NULL OR summary = ''"
        ).fetchone()[0]
        rows = db.conn.execute(
            """SELECT id, name, type, signature, parent_name, doc_comment, file, start_line, language
               FROM symbols
               WHERE summary IS NULL OR summary = ''
               ORDER BY type, file, start_line
               LIMIT ?""",
            (batch_size,),
        ).fetchall()

    if not rows:
        return json.dumps({"pending_count": 0, "batch": [], "message": "All symbols have summaries."})

    batch = []
    for r in rows:
        # Get up to 5 callee names for extra context
        callee_rows = db.conn.execute(
            """SELECT DISTINCT r.target_name
               FROM relations r
               WHERE r.source_id = ? AND r.rel_type = 'CALLS'
               LIMIT 5""",
            (r["id"],),
        ).fetchall()
        callee_names = [c["target_name"] for c in callee_rows]

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
            "callee_names": callee_names,
        })

    prompt_hint = (
        "For each symbol in the batch, generate a concise one-sentence English summary "
        "describing what the symbol does. Use the signature, parent class, doc comment, "
        "and callee names as context. Return results by calling write_summaries with "
        "a list of {id, summary} objects."
    )

    return json.dumps({
        "pending_count": total,
        "batch_size": len(batch),
        "batch": batch,
        "prompt_hint": prompt_hint,
    }, ensure_ascii=False)


def _tool_write_summaries(args: dict, db, vector_store) -> str:
    summaries = args.get("summaries", [])
    if not summaries:
        return json.dumps({"written": 0, "error": "No summaries provided"})

    written = 0
    for item in summaries:
        sid = item.get("id")
        summary = (item.get("summary") or "").strip()
        if sid and summary:
            db.conn.execute(
                "UPDATE symbols SET summary = ? WHERE id = ?", (summary, sid)
            )
            written += 1
    db.conn.commit()

    # Re-embed updated symbols so semantic search benefits immediately
    if written > 0:
        ids = [item["id"] for item in summaries if item.get("id") and item.get("summary")]
        updated_syms = []
        for sid in ids:
            sym = db.get_symbol(sid)
            if sym:
                updated_syms.append(sym)
        if updated_syms:
            vector_store.upsert_symbols(updated_syms)

    remaining = db.conn.execute(
        "SELECT COUNT(*) FROM symbols WHERE summary IS NULL OR summary = ''"
    ).fetchone()[0]

    return json.dumps({"written": written, "remaining": remaining})


def _tool_get_pending_wiki(args: dict, db, repo_root: Path) -> str:
    from reposage.indexer.pipeline import get_reposage_dir
    modules = db.get_all_modules()
    docs_dir = get_reposage_dir(repo_root) / "docs" / "modules"

    pending = []
    for m in modules:
        md_path = docs_dir / f"{m['name']}.md"
        if md_path.exists():
            continue

        # Symbols for this module
        rows = db.conn.execute(
            """SELECT name, type, signature, doc_comment, start_line, file
               FROM symbols WHERE module_id = ? AND is_public = 1
               ORDER BY type, name LIMIT 40""",
            (m["id"],),
        ).fetchall()
        symbols_text = "\n".join(
            f"- [{r['type']}] {r['name']}"
            + (f": {r['signature']}" if r.get("signature") else "")
            + (f" — {r['doc_comment'][:80]}" if r.get("doc_comment") else "")
            for r in rows
        )

        # Key relations
        rel_rows = db.conn.execute(
            """SELECT DISTINCT r.rel_type, s.name as src, r.target_name as tgt
               FROM relations r
               JOIN symbols s ON r.source_id = s.id
               WHERE s.module_id = ? AND r.rel_type IN ('EXTENDS','IMPLEMENTS','CONFORMS_TO','CALLS')
               LIMIT 20""",
            (m["id"],),
        ).fetchall()
        relations_text = "\n".join(
            f"- {r['src']} {r['rel_type']} {r['tgt']}" for r in rel_rows
        )

        pending.append({
            "id": m["id"],
            "name": m["name"],
            "files": m["files"][:10],
            "symbols_text": symbols_text or "(no public symbols)",
            "relations_text": relations_text or "(none detected)",
        })

    arch_md = get_reposage_dir(repo_root) / "docs" / "ARCHITECTURE.md"
    need_architecture = not arch_md.exists()

    module_prompt_template = (
        "You are a senior mobile engineer writing documentation.\n"
        "Given the following module information, write a concise Markdown document.\n\n"
        "Module: {module_name}\n"
        "Files: {files}\n\n"
        "Key symbols:\n{symbols}\n\n"
        "Key relationships:\n{relations}\n\n"
        "Write a Markdown document with:\n"
        "1. A one-paragraph description of this module's responsibility\n"
        "2. Key classes/protocols/functions with a one-line description each\n"
        "3. A 'How it works' section (2-4 sentences)\n"
        "4. A Mermaid diagram of main class relationships (if applicable)\n\n"
        "Be concise. No boilerplate."
    )

    arch_prompt_template = (
        "You are a senior mobile engineer writing architecture documentation.\n"
        "Given the following module summaries for '{repo_name}', write a top-level ARCHITECTURE.md.\n\n"
        "Modules:\n{modules}\n\n"
        "Write:\n"
        "1. A 2-paragraph overview of what this codebase does\n"
        "2. A module dependency diagram in Mermaid (flowchart TD)\n"
        "3. A table of modules with their responsibilities\n"
        "4. Key architectural patterns used\n\n"
        "Be concise and actionable."
    )

    if not pending and not need_architecture:
        return json.dumps({"message": "All modules have wiki docs and ARCHITECTURE.md exists."})

    return json.dumps({
        "pending_modules": len(pending),
        "modules": pending,
        "need_architecture": need_architecture,
        "repo_name": repo_root.name,
        "module_prompt_template": module_prompt_template,
        "arch_prompt_template": arch_prompt_template if need_architecture else None,
        "instructions": (
            "For each module, fill in the module_prompt_template and generate Markdown content. "
            "If need_architecture is true, collect all module summaries and fill arch_prompt_template. "
            "Then call write_wiki with the results."
        ),
    }, ensure_ascii=False)


def _tool_write_wiki(args: dict, db, repo_root: Path) -> str:
    from reposage.indexer.pipeline import get_reposage_dir
    modules = args.get("modules") or []
    architecture = args.get("architecture") or ""

    docs_dir = get_reposage_dir(repo_root) / "docs"
    modules_dir = docs_dir / "modules"
    docs_dir.mkdir(parents=True, exist_ok=True)
    modules_dir.mkdir(exist_ok=True)

    written_modules = 0
    for m in modules:
        mid = m.get("id")
        name = m.get("name", "")
        content = (m.get("content") or "").strip()
        if not name or not content:
            continue

        md_path = modules_dir / f"{name}.md"
        md_path.write_text(f"# {name}\n\n{content}", encoding="utf-8")

        # Update module summary in DB
        if mid:
            db.conn.execute(
                "UPDATE modules SET description = ?, summary = ? WHERE id = ?",
                (content[:200], content[:200], mid),
            )
        written_modules += 1

    db.conn.commit()

    architecture_written = False
    if architecture.strip():
        arch_path = docs_dir / "ARCHITECTURE.md"
        arch_path.write_text(architecture.strip(), encoding="utf-8")
        architecture_written = True

    return json.dumps({
        "written_modules": written_modules,
        "architecture_written": architecture_written,
    })
