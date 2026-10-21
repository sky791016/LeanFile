"""Physical auto-filing for a drop folder.

The drop folder is the one place a user throws files without thinking.
filing_plan() computes where each file WOULD go in a generated tree
(library_root / category / YYYY-MM / name). execute_plan() performs
the moves, updates the registry's location rows to match, and writes
a manifest that undo() can reverse move-for-move. Nothing is ever
overwritten: collisions get a " (2)" suffix. Planning is the default;
execution only happens when the caller explicitly asks.
"""

import json
import os
import shutil
import sqlite3
import time

from .autopilot import classify_all
from .core import Registry
from .nodes import get_node


def _dest_parts(by, category, atype, mtime):
    parts = []
    for key in by:
        if key == "category":
            parts.append(category or "其他文件")
        elif key == "month":
            parts.append(time.strftime("%Y-%m", time.localtime(mtime)))
        elif key == "year":
            parts.append(time.strftime("%Y", time.localtime(mtime)))
        elif key == "type":
            parts.append(atype or "file")
    return parts


def filing_plan(db_path, drop_node, library_root,
                by=("category", "month")):
    classify_all(db_path)
    reg = Registry(db_path)
    node = get_node(reg, drop_node)
    root = os.path.abspath(node["path"])
    lib = os.path.abspath(library_root)
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    rows = db.execute(
        "SELECT l.path AS path, l.mtime AS mtime, a.id AS aid, "
        "a.name AS name, a.category AS category, a.atype AS atype "
        "FROM locations l "
        "JOIN versions v ON v.blob_hash=l.hash "
        "JOIN assets a ON a.id=v.asset_id"
    ).fetchall()
    db.close()
    plan, used = [], set()
    seen_paths = set()
    for r in rows:
        path = os.path.abspath(r["path"])
        if path in seen_paths:
            continue
        seen_paths.add(path)
        if not path.startswith(root + os.sep):
            continue
        if path.startswith(lib + os.sep):
            continue
        if not os.path.exists(path):
            continue
        parts = _dest_parts(by, r["category"], r["atype"],
                            r["mtime"] or 0)
        dest_dir = os.path.join(lib, *parts) if parts else lib
        name = os.path.basename(path)
        stem, ext = os.path.splitext(name)
        dest, n = os.path.join(dest_dir, name), 2
        while dest in used or os.path.exists(dest):
            dest = os.path.join(dest_dir, f"{stem} ({n}){ext}")
            n += 1
        used.add(dest)
        plan.append({"asset_id": r["aid"], "name": name,
                     "from": path, "to": dest})
    return plan


def execute_plan(db_path, plan, manifest_path):
    db = sqlite3.connect(db_path)
    done = []
    try:
        for item in plan:
            os.makedirs(os.path.dirname(item["to"]), exist_ok=True)
            shutil.move(item["from"], item["to"])
            db.execute(
                "UPDATE locations SET path=? WHERE path=?",
                (item["to"], item["from"]),
            )
            done.append(item)
        db.commit()
    finally:
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump({"created": time.time(), "moves": done}, f,
                      ensure_ascii=False, indent=1)
        db.close()
    return len(done)


def undo(db_path, manifest_path):
    with open(manifest_path, encoding="utf-8") as f:
        data = json.load(f)
    db = sqlite3.connect(db_path)
    back = 0
    for item in reversed(data.get("moves", [])):
        src, dst = item["to"], item["from"]
        if os.path.exists(src) and not os.path.exists(dst):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.move(src, dst)
            db.execute(
                "UPDATE locations SET path=? WHERE path=?", (dst, src)
            )
            back += 1
    db.commit()
    db.close()
    data["undone_at"] = time.time()
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    return back
