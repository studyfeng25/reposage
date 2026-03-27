"""Cross-file relation resolution: fill target_id from target_name."""
import logging
from typing import List, Dict
from reposage.storage.db import RepoSageDB

logger = logging.getLogger(__name__)


def resolve_relations(db: RepoSageDB) -> int:
    """Resolve target_name → target_id for all unresolved relations."""
    resolved = db.resolve_relations()
    logger.info(f"Resolved {resolved} relations")
    return resolved


def cluster_files_into_modules(db: RepoSageDB) -> List[Dict]:
    """
    Simple heuristic: group files by top-level directory.
    Returns list of {id, name, files} dicts.
    """
    files = db.get_indexed_files()
    groups: Dict[str, List[str]] = {}

    for f in files:
        parts = f.replace("\\", "/").split("/")
        if len(parts) >= 2:
            group_key = parts[0]
        else:
            group_key = "root"
        groups.setdefault(group_key, []).append(f)

    modules = []
    for name, file_list in sorted(groups.items()):
        import hashlib
        mod_id = hashlib.md5(name.encode()).hexdigest()[:12]
        modules.append({"id": mod_id, "name": name, "files": file_list})

    return modules
