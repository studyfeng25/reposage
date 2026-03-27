"""Java tree-sitter queries and symbol extraction."""
from typing import List, Tuple, Optional
from reposage.indexer.models import Symbol, Relation

EXTENSIONS = [".java"]


def extract_symbols(tree, file_rel: str, source: bytes, language) -> Tuple[List[Symbol], List[Relation]]:
    """Extract symbols and relations from a Java AST."""
    symbols: List[Symbol] = []
    relations: List[Relation] = []

    root = tree.root_node
    class_stack: List[Tuple[str, str]] = []  # (name, id)
    package_name: str = ""

    def node_text(node) -> str:
        return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")

    def extract_doc_comment(node) -> str:
        prev = node.prev_named_sibling
        if prev and prev.type in ("block_comment", "line_comment"):
            text = node_text(prev).strip()
            if text.startswith("/**") or text.startswith("//"):
                return text
        return ""

    def is_public(node) -> bool:
        for child in node.children:
            if child.type == "modifiers":
                return "public" in node_text(child)
        return False

    def get_name_field(node, field="name") -> Optional[str]:
        n = node.child_by_field_name(field)
        return node_text(n) if n else None

    def walk(node, depth=0):
        nonlocal package_name
        ntype = node.type

        # Package declaration
        if ntype == "package_declaration":
            for child in node.children:
                if child.type in ("identifier", "scoped_identifier"):
                    package_name = node_text(child)
            return

        # Import
        elif ntype == "import_declaration":
            for child in node.children:
                if child.type in ("identifier", "scoped_identifier"):
                    imp = node_text(child)
                    if class_stack:
                        relations.append(Relation(
                            source_id=class_stack[-1][1],
                            target_name=imp,
                            rel_type="IMPORTS",
                            file=file_rel,
                            line=node.start_point[0] + 1,
                            confidence=0.9,
                        ))
                    break

        # Class / Interface / Enum / Annotation
        elif ntype in ("class_declaration", "interface_declaration",
                       "enum_declaration", "annotation_type_declaration",
                       "record_declaration"):
            name = get_name_field(node)
            if not name:
                for child in node.children:
                    walk(child, depth + 1)
                return

            type_map = {
                "class_declaration": "class",
                "interface_declaration": "interface",
                "enum_declaration": "enum",
                "annotation_type_declaration": "annotation",
                "record_declaration": "class",
            }
            sym = Symbol(
                name=name,
                type=type_map[ntype],
                file=file_rel,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                language="java",
                doc_comment=extract_doc_comment(node),
                is_public=is_public(node),
                parent_name=class_stack[-1][0] if class_stack else "",
            )
            symbols.append(sym)

            # Superclass
            super_node = node.child_by_field_name("superclass")
            if super_node:
                for child in super_node.children:
                    if child.type in ("type_identifier", "identifier"):
                        relations.append(Relation(
                            source_id=sym.id,
                            target_name=node_text(child),
                            rel_type="EXTENDS",
                            file=file_rel,
                            line=node.start_point[0] + 1,
                        ))

            # Interfaces
            interfaces_node = node.child_by_field_name("interfaces")
            if interfaces_node:
                for child in interfaces_node.children:
                    if child.type == "type_list":
                        for iface in child.children:
                            if iface.type in ("type_identifier", "identifier"):
                                relations.append(Relation(
                                    source_id=sym.id,
                                    target_name=node_text(iface),
                                    rel_type="IMPLEMENTS",
                                    file=file_rel,
                                    line=node.start_point[0] + 1,
                                ))

            class_stack.append((name, sym.id))
            for child in node.children:
                walk(child, depth + 1)
            class_stack.pop()
            return

        # Method
        elif ntype in ("method_declaration", "constructor_declaration"):
            name = get_name_field(node)
            if not name:
                for child in node.children:
                    walk(child, depth + 1)
                return

            # Build signature
            params_node = node.child_by_field_name("parameters")
            params_text = node_text(params_node) if params_node else "()"
            ret_node = node.child_by_field_name("type")
            ret_text = node_text(ret_node) if ret_node else "void"
            signature = f"{ret_text} {name}{params_text}"

            sym = Symbol(
                name=name,
                type="method" if ntype == "method_declaration" else "constructor",
                file=file_rel,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                language="java",
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

        # Field
        elif ntype == "field_declaration":
            for child in node.children:
                if child.type == "variable_declarator":
                    name_node = child.child_by_field_name("name")
                    if name_node:
                        sym = Symbol(
                            name=node_text(name_node),
                            type="field",
                            file=file_rel,
                            start_line=node.start_point[0] + 1,
                            end_line=node.end_point[0] + 1,
                            language="java",
                            is_public=is_public(node),
                            parent_name=class_stack[-1][0] if class_stack else "",
                        )
                        symbols.append(sym)

        for child in node.children:
            walk(child, depth + 1)

    def _extract_calls(node, source_id: str, file_rel: str, source: bytes, relations: List[Relation]):
        ntype = node.type
        if ntype == "method_invocation":
            name_node = node.child_by_field_name("name")
            if name_node:
                relations.append(Relation(
                    source_id=source_id,
                    target_name=node_text(name_node),
                    rel_type="CALLS",
                    file=file_rel,
                    line=node.start_point[0] + 1,
                    confidence=0.85,
                ))
        elif ntype == "object_creation_expression":
            type_node = node.child_by_field_name("type")
            if type_node:
                relations.append(Relation(
                    source_id=source_id,
                    target_name=node_text(type_node),
                    rel_type="CALLS",
                    file=file_rel,
                    line=node.start_point[0] + 1,
                    confidence=0.8,
                ))
        for child in node.children:
            _extract_calls(child, source_id, file_rel, source, relations)

    walk(root)
    return symbols, relations
