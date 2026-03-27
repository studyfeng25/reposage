"""Data models for parsed symbols and relations."""
from dataclasses import dataclass, field
from typing import Optional
import hashlib


@dataclass
class Symbol:
    name: str
    type: str          # class/interface/protocol/method/function/property/enum
    file: str          # relative path from repo root
    start_line: int
    end_line: int
    language: str      # objc/swift/java
    signature: str = ""
    doc_comment: str = ""
    is_public: bool = True
    parent_name: str = ""   # enclosing class/interface name
    id: str = ""

    def __post_init__(self):
        if not self.id:
            raw = f"{self.type}:{self.file}:{self.name}:{self.start_line}"
            self.id = hashlib.md5(raw.encode()).hexdigest()[:16]


@dataclass
class Relation:
    source_id: str
    target_name: str       # unresolved name
    rel_type: str          # CALLS/EXTENDS/IMPLEMENTS/IMPORTS/HAS_METHOD/CONFORMS_TO
    file: str
    line: int
    confidence: float = 1.0
    target_id: str = ""    # filled after resolution
    id: str = ""

    def __post_init__(self):
        if not self.id:
            raw = f"{self.source_id}:{self.target_name}:{self.rel_type}:{self.line}"
            self.id = hashlib.md5(raw.encode()).hexdigest()[:16]
