"""Storage nodes: NAS is one node among equals.

A node is a reachable storage location (local disk, NAS share,
external drive, remote machine). The registry tracks, for every
blob, which nodes physically hold it. That single distribution map
powers cross-node dedup, final-asset coverage checks (is every
final asset on >= 2 nodes?) and replication plans.
"""
import os
import shutil
import time

from .core import hash_file

SKIP_DIRS = {"#recycle", "@eaDir", ".Spotlight-V100", ".Trashes", "node_modules"}


def ensure_tables(reg):
    reg.db.executescript(
        """
        CREATE TABLE IF NOT EXISTS nodes(
          name TEXT PRIMARY KEY, path TEXT, kind TEXT, created REAL);
        CREATE TABLE IF NOT EXISTS locations(
          path TEXT PRIMARY KEY, hash TEXT, node TEXT,
          size INTEGER, mtime REAL);
        CREATE INDEX IF NOT EXISTS idx_locations_hash ON locations(hash);
        CREATE INDEX IF NOT EXISTS idx_locations_node ON locations(node);
        """
    )
    reg.db.commit()


def add_node(reg, name, path, kind="local"):
    ensure_tables(reg)
    reg.db.execute(
        "INSERT OR REPLACE INTO nodes VALUES (?,?,?,?)",
        (name, os.path.abspath(path), kind, time.time()),
    )
    reg.db.commit()
    return name


def list_nodes(reg):
    ensure_tables(reg)
    return reg.db.execute("SELECT * FROM nodes ORDER BY name").fetchall()


def get_node(reg, name):
    ensure_tables(reg)
    row = reg.db.execute(
        "SELECT * FROM nodes WHERE name=?", (name,)
    ).fetchone()
    if row is None:
        raise ValueError("unknown node: " + name)
    return row


def _record_location(reg, path, digest, node, size, mtime):
    reg.db.execute(
        "INSERT OR REPLACE INTO locations VALUES (?,?,?,?,?)",
        (os.path.abspath(path), digest, node, size, mtime),
    )


def scan_node(reg, node_name, extensions=None):
    """Register every file under the node root, in place.

    Incremental: a file whose size+mtime match the last scan is
    skipped without hashing. New/changed files are hashed and
    registered as assets (asset_key scoped by node + relpath).
    """
    ensure_tables(reg)
    node = get_node(reg, node_name)
    root = node["path"]
    stats = {"seen": 0, "skipped": 0, "registered": 0, "errors": 0}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if extensions and not fn.lower().endswith(extensions):
                continue
            full = os.path.join(dirpath, fn)
            stats["seen"] += 1
            try:
                st = os.stat(full)
            except OSError:
                # broken symlink / vanished mid-scan: count, never crash
                stats["errors"] += 1
                continue
            prev = reg.db.execute(
                "SELECT * FROM locations WHERE path=?", (os.path.abspath(full),)
            ).fetchone()
            if prev and prev["size"] == st.st_size and abs(prev["mtime"] - st.st_mtime) < 1:
                stats["skipped"] += 1
                continue
            digest = hash_file(full)
            rel = os.path.relpath(full, root)
            manifest = {
                "asset_key": f"scan::{node_name}::{rel}",
                "name": os.path.splitext(fn)[0],
                "project": "节点扫描/" + node_name,
            }
            reg.register(full, manifest)
            _record_location(reg, full, digest, node_name, st.st_size, st.st_mtime)
            stats["registered"] += 1
    reg.db.commit()
    return stats


def coverage(reg, min_nodes=2):
    """Final/published assets: protected (>=min_nodes) vs at-risk."""
    ensure_tables(reg)
    rows = reg.db.execute(
        "SELECT a.id, a.name, a.state, "
        "(SELECT blob_hash FROM versions v WHERE v.asset_id=a.id "
        " ORDER BY seq DESC LIMIT 1) AS blob "
        "FROM assets a WHERE a.state IN ('final','published')"
    ).fetchall()
    protected, at_risk = [], []
    for r in rows:
        nodes = reg.db.execute(
            "SELECT DISTINCT node FROM locations WHERE hash=?", (r["blob"],)
        ).fetchall()
        entry = {"asset": r["name"], "nodes": [n["node"] for n in nodes]}
        (protected if len(nodes) >= min_nodes else at_risk).append(entry)
    return {"protected": protected, "at_risk": at_risk}


def replication_plan(reg, target_node):
    """Final assets whose latest blob has no copy on target_node."""
    ensure_tables(reg)
    target = get_node(reg, target_node)
    cov = coverage(reg, min_nodes=1)
    plan = []
    rows = reg.db.execute(
        "SELECT a.name, "
        "(SELECT blob_hash FROM versions v WHERE v.asset_id=a.id "
        " ORDER BY seq DESC LIMIT 1) AS blob "
        "FROM assets a WHERE a.state IN ('final','published')"
    ).fetchall()
    for r in rows:
        on_target = reg.db.execute(
            "SELECT COUNT(*) AS c FROM locations WHERE hash=? AND node=?",
            (r["blob"], target_node),
        ).fetchone()["c"]
        if on_target:
            continue
        src = reg.db.execute(
            "SELECT path FROM locations WHERE hash=? LIMIT 1", (r["blob"],)
        ).fetchone()
        if src is None:
            continue
        dest = os.path.join(
            target["path"],
            "LeanFileVault",
            r["blob"][:2],
            r["blob"][:16] + "_" + os.path.basename(src["path"]),
        )
        plan.append(
            {"asset": r["name"], "hash": r["blob"], "src": src["path"], "dest": dest}
        )
    return plan


def replicate(reg, target_node, execute=False):
    """Plan by default. With execute=True: copy + hash-verify + register."""
    plan = replication_plan(reg, target_node)
    if not execute:
        return {"planned": plan, "done": []}
    done = []
    for item in plan:
        os.makedirs(os.path.dirname(item["dest"]), exist_ok=True)
        shutil.copy2(item["src"], item["dest"])
        if hash_file(item["dest"]) != item["hash"]:
            os.remove(item["dest"])
            raise IOError("hash mismatch after copy: " + item["dest"])
        st = os.stat(item["dest"])
        _record_location(reg, item["dest"], item["hash"], target_node, st.st_size, st.st_mtime)
        reg.db.execute(
            "INSERT OR IGNORE INTO blob_locations VALUES (?,?)",
            (item["hash"], os.path.abspath(item["dest"])),
        )
        done.append(item)
    reg.db.commit()
    return {"planned": plan, "done": done}
