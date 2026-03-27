"""MCP Server — exposes RepoSage knowledge graph to AI agents."""
import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


async def start_mcp_server(repo_root: Path):
    """Entry point: start the MCP stdio server for a repo."""
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp import types

    db_path = repo_root / ".reposage" / "index.db"
    if not db_path.exists():
        raise FileNotFoundError(
            f"Repository not indexed yet. Run: reposage analyze {repo_root}"
        )

    from reposage.storage.db import RepoSageDB
    from reposage.storage.vector_store import VectorStore

    db = RepoSageDB(db_path)
    vector_store = VectorStore(repo_root / ".reposage" / "vectors", repo_root.name)

    server = Server("reposage")

    # ── Tool Handlers ─────────────────────────────────────────────────────────

    @server.list_tools()
    async def list_tools():
        return [
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
                    },
                    "required": ["entry_point"],
                },
            ),
            types.Tool(
                name="ask",
                description=(
                    "RAG-powered Q&A about the codebase. "
                    "Searches docs + symbols and answers in natural language."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                    },
                    "required": ["question"],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
        try:
            result = await _dispatch(name, arguments, db, vector_store, repo_root)
            return [types.TextContent(type="text", text=result)]
        except Exception as e:
            logger.exception(f"Tool {name} failed")
            return [types.TextContent(type="text", text=f"Error: {e}")]

    # ── Resource Handlers ─────────────────────────────────────────────────────

    @server.list_resources()
    async def list_resources():
        return [
            types.Resource(
                uri="reposage://repo/context",
                name="Repository Context",
                description="Stats, index status, module list",
                mimeType="application/json",
            ),
            types.Resource(
                uri="reposage://modules",
                name="All Modules",
                description="Module topology with exported symbols",
                mimeType="application/json",
            ),
        ]

    @server.read_resource()
    async def read_resource(uri: str) -> str:
        if uri == "reposage://repo/context":
            stats = db.get_stats()
            modules = [m["name"] for m in db.get_all_modules()]
            return json.dumps({"repo": repo_root.name, "stats": stats, "modules": modules}, indent=2)
        elif uri == "reposage://modules":
            modules = db.get_all_modules()
            return json.dumps(modules, indent=2, ensure_ascii=False)
        return json.dumps({"error": "Unknown resource"})

    # ── Start ─────────────────────────────────────────────────────────────────

    async with stdio_server() as (read_stream, write_stream):
        from mcp.server.models import InitializationOptions
        import mcp.types as mcp_types
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="reposage",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=mcp_types.NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


# ── Tool implementations ───────────────────────────────────────────────────────

async def _dispatch(name: str, args: dict, db, vector_store, repo_root: Path) -> str:
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
        return await _tool_ask(args, db, vector_store, repo_root)
    return f"Unknown tool: {name}"


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


async def _tool_ask(args: dict, db, vector_store, repo_root: Path) -> str:
    question = args["question"]

    # Search for relevant symbols
    fts = db.search_symbols_fts(question, limit=10)
    sem = vector_store.search(question, limit=10)

    context_parts = []
    seen = set()

    for s in fts + sem:
        sid = s.get("id") or s.get("id")
        if sid and sid not in seen:
            seen.add(sid)
            sig = s.get("signature") or ""
            doc = s.get("doc_comment") or ""
            summary = s.get("summary") or ""
            context_parts.append(
                f"[{s.get('type','?')}] {s.get('name','?')} in {s.get('file','?')}:{s.get('start_line','?')}"
                + (f"\n  Signature: {sig}" if sig else "")
                + (f"\n  Doc: {doc[:150]}" if doc else "")
                + (f"\n  Summary: {summary[:150]}" if summary else "")
            )

    # Also include wiki docs if available
    wiki_context = ""
    arch_md = repo_root / "docs" / "ARCHITECTURE.md"
    if arch_md.exists():
        wiki_context = arch_md.read_text(encoding="utf-8")[:2000]

    context = "\n\n".join(context_parts[:15])
    if wiki_context:
        context = f"Architecture Overview:\n{wiki_context}\n\nRelevant Symbols:\n{context}"

    import os
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return (
            f"**Question**: {question}\n\n"
            f"**Context** (set ANTHROPIC_API_KEY for AI answers):\n{context}"
        )

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=1024,
            system=(
                "You are a code expert. Answer questions about the codebase concisely. "
                "Reference specific file paths and line numbers when relevant. "
                "Use the provided context to give accurate answers."
            ),
            messages=[
                {
                    "role": "user",
                    "content": f"Codebase context:\n{context}\n\nQuestion: {question}",
                }
            ],
        )
        return message.content[0].text
    except Exception as e:
        return f"AI answer failed ({e}). Context:\n{context}"
