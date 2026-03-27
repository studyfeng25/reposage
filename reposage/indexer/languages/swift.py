"""Swift tree-sitter queries and symbol extraction."""
from typing import List, Tuple, Optional
from reposage.indexer.models import Symbol, Relation

EXTENSIONS = [".swift"]


def extract_symbols(tree, file_rel: str, source: bytes, language) -> Tuple[List[Symbol], List[Relation]]:
    """Extract symbols and relations from a Swift AST."""
    symbols: List[Symbol] = []
    relations: List[Relation] = []

    root = tree.root_node

    # Stack for tracking enclosing type context
    class_stack: List[Tuple[str, str]] = []  # (name, id)

    def node_text(node) -> str:
        return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")

    def extract_doc_comment(node) -> str:
        prev = node.prev_named_sibling
        if prev and prev.type in ("comment", "multiline_comment"):
            text = node_text(prev).strip()
            if text.startswith("///") or text.startswith("/**"):
                return text
        return ""

    def is_public(node) -> bool:
        """Check if node has public/open modifier."""
        for child in node.children:
            if child.type == "modifiers":
                mods = node_text(child)
                return any(m in mods for m in ("public", "open"))
        return True  # Swift default: internal (visible within module)

    def get_name(node, field="name") -> Optional[str]:
        n = node.child_by_field_name(field)
        if n:
            return node_text(n)
        # Fallback: first type_identifier or identifier child
        for child in node.children:
            if child.type in ("type_identifier", "identifier"):
                return node_text(child)
        return None

    def walk(node, depth=0):
        ntype = node.type

        # --- Class / Struct / Enum / Actor ---
        if ntype in ("class_declaration", "struct_declaration",
                     "enum_declaration", "actor_declaration"):
            name = get_name(node)
            if not name:
                for child in node.children:
                    walk(child, depth + 1)
                return

            type_map = {
                "class_declaration": "class",
                "struct_declaration": "struct",
                "enum_declaration": "enum",
                "actor_declaration": "class",
            }
            sym = Symbol(
                name=name,
                type=type_map[ntype],
                file=file_rel,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                language="swift",
                doc_comment=extract_doc_comment(node),
                is_public=is_public(node),
                parent_name=class_stack[-1][0] if class_stack else "",
            )
            symbols.append(sym)

            # Inheritance / protocol conformance
            for child in node.children:
                if child.type == "type_inheritance_clause":
                    for inh in child.children:
                        if inh.type in ("type_identifier", "user_type"):
                            target = node_text(inh).split(".")[0]
                            relations.append(Relation(
                                source_id=sym.id,
                                target_name=target,
                                rel_type="EXTENDS",
                                file=file_rel,
                                line=node.start_point[0] + 1,
                                confidence=0.9,
                            ))

            class_stack.append((name, sym.id))
            for child in node.children:
                walk(child, depth + 1)
            class_stack.pop()
            return

        # --- Extension ---
        elif ntype == "extension_declaration":
            name = get_name(node)
            if name:
                sym = Symbol(
                    name=name,
                    type="extension",
                    file=file_rel,
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    language="swift",
                    is_public=True,
                )
                symbols.append(sym)
                class_stack.append((name, sym.id))
                for child in node.children:
                    walk(child, depth + 1)
                class_stack.pop()
                return

        # --- Protocol ---
        elif ntype == "protocol_declaration":
            name = get_name(node)
            if name:
                sym = Symbol(
                    name=name,
                    type="protocol",
                    file=file_rel,
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    language="swift",
                    doc_comment=extract_doc_comment(node),
                    is_public=is_public(node),
                )
                symbols.append(sym)

        # --- Function / Method ---
        elif ntype == "function_declaration":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = node_text(name_node)
                # Build signature from parameters
                params_node = node.child_by_field_name("parameters")
                params_text = node_text(params_node) if params_node else "()"
                ret_node = node.child_by_field_name("return_type")
                ret_text = (" -> " + node_text(ret_node)) if ret_node else ""
                signature = f"func {name}{params_text}{ret_text}"

                sym = Symbol(
                    name=name,
                    type="method" if class_stack else "function",
                    file=file_rel,
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    language="swift",
                    signature=signature,
                    doc_comment=extract_doc_comment(node),
                    is_public=is_public(node),
                    parent_name=class_stack[-1][0] if class_stack else "",
                )
                symbols.append(sym)

                if class_stack:
                    relations.append(Relation(
                        source_id=class_stack[-1][1],
                        target_name=name,
                        rel_type="HAS_METHOD",
                        file=file_rel,
                        line=node.start_point[0] + 1,
                        target_id=sym.id,
                    ))

                # Extract calls from body
                body = node.child_by_field_name("body")
                if body:
                    _extract_calls(body, sym.id, file_rel, source, relations)
                return

        # --- Initializer ---
        elif ntype == "init_declaration":
            sym = Symbol(
                name="init",
                type="method",
                file=file_rel,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                language="swift",
                signature="init()",
                parent_name=class_stack[-1][0] if class_stack else "",
            )
            symbols.append(sym)
            if class_stack:
                relations.append(Relation(
                    source_id=class_stack[-1][1],
                    target_name="init",
                    rel_type="HAS_METHOD",
                    file=file_rel,
                    line=node.start_point[0] + 1,
                    target_id=sym.id,
                ))

        # --- Property ---
        elif ntype in ("variable_declaration", "constant_declaration"):
            for child in node.children:
                if child.type == "pattern":
                    for sub in child.children:
                        if sub.type == "identifier":
                            name = node_text(sub)
                            sym = Symbol(
                                name=name,
                                type="property",
                                file=file_rel,
                                start_line=node.start_point[0] + 1,
                                end_line=node.end_point[0] + 1,
                                language="swift",
                                parent_name=class_stack[-1][0] if class_stack else "",
                            )
                            symbols.append(sym)
                            break

        # --- Import ---
        elif ntype == "import_declaration":
            for child in node.children:
                if child.type in ("identifier", "scoped_identifier"):
                    module = node_text(child)
                    if class_stack:
                        relations.append(Relation(
                            source_id=class_stack[-1][1],
                            target_name=module,
                            rel_type="IMPORTS",
                            file=file_rel,
                            line=node.start_point[0] + 1,
                            confidence=0.9,
                        ))
                    break

        for child in node.children:
            walk(child, depth + 1)

    def _extract_calls(node, source_id: str, file_rel: str, source: bytes, relations: List[Relation]):
        if node.type == "call_expression":
            func = node.child_by_field_name("function")
            if func:
                # Handle chained: foo.bar() → bar
                if func.type == "navigation_expression":
                    suffix = func.child_by_field_name("suffix")
                    if suffix:
                        for child in suffix.children:
                            if child.type == "identifier":
                                relations.append(Relation(
                                    source_id=source_id,
                                    target_name=node_text(child),
                                    rel_type="CALLS",
                                    file=file_rel,
                                    line=node.start_point[0] + 1,
                                    confidence=0.8,
                                ))
                                break
                elif func.type == "identifier":
                    relations.append(Relation(
                        source_id=source_id,
                        target_name=node_text(func),
                        rel_type="CALLS",
                        file=file_rel,
                        line=node.start_point[0] + 1,
                        confidence=0.85,
                    ))
        for child in node.children:
            _extract_calls(child, source_id, file_rel, source, relations)

    walk(root)
    return symbols, relations
