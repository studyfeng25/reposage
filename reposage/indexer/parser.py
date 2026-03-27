"""Multi-language parser using tree-sitter."""
from pathlib import Path
from typing import List, Tuple, Optional
import logging

from reposage.indexer.models import Symbol, Relation

logger = logging.getLogger(__name__)

# Language extension mapping
LANG_EXTENSIONS = {
    "objc": [".m", ".h", ".mm"],
    "swift": [".swift"],
    "java": [".java"],
}

ALL_EXTENSIONS = {ext for exts in LANG_EXTENSIONS.values() for ext in exts}

_parsers: dict = {}
_languages: dict = {}


def _get_parser(lang: str):
    """Lazily initialize tree-sitter parser for a language."""
    if lang in _parsers:
        return _parsers[lang], _languages[lang]

    try:
        from tree_sitter import Language, Parser

        if lang == "objc":
            from tree_sitter_languages import get_language
            language = get_language("objc")
        elif lang == "swift":
            import tree_sitter_swift
            language = Language(tree_sitter_swift.language(), "swift")
        elif lang == "java":
            from tree_sitter_languages import get_language
            language = get_language("java")
        else:
            raise ValueError(f"Unsupported language: {lang}")

        parser = Parser()
        parser.set_language(language)
        _parsers[lang] = parser
        _languages[lang] = language
        return parser, language
    except Exception as e:
        logger.error(f"Failed to initialize parser for {lang}: {e}")
        raise


def detect_language(file_path: str) -> Optional[str]:
    """Detect language from file extension."""
    ext = Path(file_path).suffix.lower()
    for lang, exts in LANG_EXTENSIONS.items():
        if ext in exts:
            return lang
    return None


def parse_file(file_path: Path, repo_root: Path) -> Tuple[List[Symbol], List[Relation]]:
    """Parse a single file and return symbols + relations."""
    rel_path = str(file_path.relative_to(repo_root))
    lang = detect_language(str(file_path))

    if not lang:
        return [], []

    try:
        source = file_path.read_bytes()
    except Exception as e:
        logger.warning(f"Cannot read {file_path}: {e}")
        return [], []

    try:
        parser, language = _get_parser(lang)
        tree = parser.parse(source)
    except Exception as e:
        logger.warning(f"Parse failed for {file_path}: {e}")
        return [], []

    try:
        if lang == "objc":
            from reposage.indexer.languages.objc import extract_symbols
        elif lang == "swift":
            from reposage.indexer.languages.swift import extract_symbols
        elif lang == "java":
            from reposage.indexer.languages.java import extract_symbols
        else:
            return [], []

        symbols, relations = extract_symbols(tree, rel_path, source, language)
        return symbols, relations

    except Exception as e:
        logger.warning(f"Symbol extraction failed for {file_path}: {e}")
        return [], []


def iter_source_files(repo_root: Path):
    """Yield all supported source files in a repository."""
    EXCLUDE_DIRS = {
        ".git", "node_modules", "Pods", "build", "DerivedData",
        ".build", "vendor", "__pycache__", ".reposage",
    }
    for path in repo_root.rglob("*"):
        if path.is_file():
            if any(part in EXCLUDE_DIRS for part in path.parts):
                continue
            if path.suffix.lower() in ALL_EXTENSIONS:
                yield path
