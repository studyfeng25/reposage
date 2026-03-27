"""Objective-C tree-sitter queries and symbol extraction."""
from typing import List, Tuple
from reposage.indexer.models import Symbol, Relation

EXTENSIONS = [".m", ".h", ".mm"]

# S-expression queries for Objective-C
CLASS_QUERY = """
(class_interface
  name: (identifier) @name) @definition

(class_implementation
  name: (identifier) @name) @definition

(category_interface
  name: (identifier) @name
  category: (identifier)? @category) @definition

(category_implementation
  name: (identifier) @name) @definition
"""

PROTOCOL_QUERY = """
(protocol_declaration
  name: (identifier) @name) @definition
"""

METHOD_QUERY = """
(method_declaration
  (method_type) @method_type
  (method_selector
    (keyword_declarator
      keyword: (identifier) @first_keyword)?)
  (method_selector
    (identifier) @simple_name)?) @definition

(method_definition
  (method_type) @method_type
  (method_selector
    (keyword_declarator
      keyword: (identifier) @first_keyword)?)
  (method_selector
    (identifier) @simple_name)?) @definition
"""

PROPERTY_QUERY = """
(property_declaration
  (type_name) @prop_type
  declarator: (identifier) @name) @definition
"""

CALL_QUERY = """
(message_expression
  receiver: (_) @receiver
  (keyword_argument
    keyword: (identifier) @selector)?) @call

(message_expression
  receiver: (_) @receiver
  (identifier) @simple_selector) @simple_call
"""

IMPORT_QUERY = """
(preproc_import
  path: (string_literal) @path) @import

(preproc_import
  path: (system_lib_string) @path) @import
"""

INHERIT_QUERY = """
(class_interface
  name: (identifier) @class_name
  superclass: (identifier) @superclass) @heritage

(class_interface
  name: (identifier) @class_name
  (protocol_reference_list
    (identifier) @protocol)) @protocol_conformance
"""


def extract_symbols(tree, file_rel: str, source: bytes, language) -> Tuple[List[Symbol], List[Relation]]:
    """Extract symbols and relations from an ObjC AST."""
    symbols: List[Symbol] = []
    relations: List[Relation] = []

    root = tree.root_node
    current_class: Optional[str] = None
    current_class_id: Optional[str] = None

    def node_text(node) -> str:
        return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")

    def extract_doc_comment(node) -> str:
        """Look for a preceding block comment or line comment."""
        prev = node.prev_named_sibling
        if prev and prev.type in ("comment",):
            text = node_text(prev).strip()
            if text.startswith("/**") or text.startswith("///") or text.startswith("//"):
                return text
        return ""

    def walk(node, depth=0):
        nonlocal current_class, current_class_id

        ntype = node.type

        # --- Class / Category / Protocol ---
        if ntype in ("class_interface", "class_implementation",
                     "category_interface", "category_implementation"):
            name_node = node.child_by_field_name("name")
            if name_node:
                name = node_text(name_node)
                sym_type = "class"
                sym = Symbol(
                    name=name,
                    type=sym_type,
                    file=file_rel,
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    language="objc",
                    doc_comment=extract_doc_comment(node),
                    is_public=True,
                )
                symbols.append(sym)

                # Superclass relation
                super_node = node.child_by_field_name("superclass")
                if super_node:
                    relations.append(Relation(
                        source_id=sym.id,
                        target_name=node_text(super_node),
                        rel_type="EXTENDS",
                        file=file_rel,
                        line=node.start_point[0] + 1,
                    ))

                # Protocol conformance
                for child in node.children:
                    if child.type == "protocol_reference_list":
                        for proto in child.children:
                            if proto.type == "identifier":
                                relations.append(Relation(
                                    source_id=sym.id,
                                    target_name=node_text(proto),
                                    rel_type="CONFORMS_TO",
                                    file=file_rel,
                                    line=node.start_point[0] + 1,
                                ))

                old_class, old_class_id = current_class, current_class_id
                current_class, current_class_id = name, sym.id
                for child in node.children:
                    walk(child, depth + 1)
                current_class, current_class_id = old_class, old_class_id
                return

        elif ntype == "protocol_declaration":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = node_text(name_node)
                sym = Symbol(
                    name=name,
                    type="protocol",
                    file=file_rel,
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    language="objc",
                    doc_comment=extract_doc_comment(node),
                    is_public=True,
                )
                symbols.append(sym)

        # --- Methods ---
        elif ntype in ("method_declaration", "method_definition"):
            # Build selector string from AST
            selector_parts = []
            method_type_prefix = "-"

            for child in node.children:
                if child.type == "instance_scope":
                    method_type_prefix = "-"
                elif child.type == "class_scope":
                    method_type_prefix = "+"
                elif child.type == "keyword_selector":
                    # Multi-part selector: keyboardWillChangeFrame:animated:
                    for kd in child.children:
                        if kd.type == "keyword_declarator":
                            for sub in kd.children:
                                if sub.type == "identifier":
                                    selector_parts.append(node_text(sub) + ":")
                                    break
                elif child.type == "unary_selector":
                    # Simple selector: viewDidLoad
                    for sub in child.children:
                        if sub.type == "identifier":
                            selector_parts.append(node_text(sub))
                            break
                elif child.type == "identifier" and not selector_parts:
                    # Direct identifier child (some tree-sitter-objc versions)
                    selector_parts.append(node_text(child))

            selector = "".join(selector_parts) if selector_parts else "unknown"
            signature = f"{method_type_prefix}({selector})"

            sym = Symbol(
                name=selector,
                type="method",
                file=file_rel,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                language="objc",
                signature=signature,
                doc_comment=extract_doc_comment(node),
                is_public=True,
                parent_name=current_class or "",
            )
            symbols.append(sym)

            if current_class_id:
                relations.append(Relation(
                    source_id=current_class_id,
                    target_name=selector,
                    rel_type="HAS_METHOD",
                    file=file_rel,
                    line=node.start_point[0] + 1,
                    target_id=sym.id,
                    confidence=1.0,
                ))

            # Walk body for message sends
            for child in node.children:
                if child.type == "compound_statement":
                    _extract_calls(child, sym.id, file_rel, source, relations)
            return

        # --- Property ---
        elif ntype == "property_declaration":
            for child in node.children:
                if child.type in ("identifier", "type_identifier"):
                    name = node_text(child)
                    sym = Symbol(
                        name=name,
                        type="property",
                        file=file_rel,
                        start_line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                        language="objc",
                        is_public=True,
                        parent_name=current_class or "",
                    )
                    symbols.append(sym)
                    break

        # --- Import ---
        elif ntype == "preproc_import":
            path_node = node.child_by_field_name("path")
            if path_node:
                path = node_text(path_node).strip('"<> ')
                if current_class_id:
                    relations.append(Relation(
                        source_id=current_class_id,
                        target_name=path,
                        rel_type="IMPORTS",
                        file=file_rel,
                        line=node.start_point[0] + 1,
                        confidence=0.9,
                    ))

        for child in node.children:
            walk(child, depth + 1)

    def _extract_calls(node, source_id: str, file_rel: str, source: bytes, relations: List[Relation]):
        """Recursively extract message sends from a method body."""
        if node.type == "message_expression":
            # Get the first keyword (selector)
            for child in node.children:
                if child.type == "keyword_argument":
                    kw = child.child_by_field_name("keyword")
                    if kw:
                        selector = node_text(kw) + ":"
                        relations.append(Relation(
                            source_id=source_id,
                            target_name=selector,
                            rel_type="CALLS",
                            file=file_rel,
                            line=node.start_point[0] + 1,
                            confidence=0.8,
                        ))
                        break
                elif child.type == "identifier" and child != node.children[0]:
                    relations.append(Relation(
                        source_id=source_id,
                        target_name=node_text(child),
                        rel_type="CALLS",
                        file=file_rel,
                        line=node.start_point[0] + 1,
                        confidence=0.7,
                    ))
                    break
        for child in node.children:
            _extract_calls(child, source_id, file_rel, source, relations)

    walk(root)
    return symbols, relations
