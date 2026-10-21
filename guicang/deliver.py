"""Delivery features (2026-10-22): conversation bundles + protect copies.

- export_bundle: gather what one conversation produced - each asset's
  latest version *within that conversation* - into one clean folder
  with a manifest, ready to hand to someone.
- protect_run: assets in the protect importance class whose best blob
  lives on fewer than 2 nodes get a verified copy on a target node.
  Plan by default; execute=True performs the copies.
"""

import json
import os
import re
import shutil
import time

from .core import Registry, hash_file
from . import nodes as nodes_mod
from .autopilot import protect_plan, get_rules


def _slug(text, maxlen=36):
    s = re.sub(r"[^\w一-鿿-]+", "-", (text or "bundle").strip())
    return s.strip("-")[:maxlen] or "bundle"


def _src_path(db, blob):
    row = db.execute(
        "SELECT path FROM locations WHERE hash=?", (blob,)
    ).fetchall()
    for r in row:
        if os.path.exists(r["path"]):
            return r["path"]
    row = db.execute(
        "SELECT path FROM blob_locations WHERE hash=?", (blob,)
    ).fetchall()
    for r in row:
        if os.path.exists(r["path"]):
            return r["path"]
    return None


def _conversation_assets(db, conv_id):
    rows = db.execute(
        "SELECT a.id AS aid, a.name, a.atype, a.state, v.seq, v.blob_hash "
        "FROM provenance p JOIN versions v ON v.id=p.version_id "
        "JOIN assets a ON a.id=v.asset_id WHERE p.conversation_id=?",
        (conv_id,),
    ).fetchall()
    best = {}
    for r in rows:
        cur = best.get(r["aid"])
        if cur is None or r["seq"] > cur["seq"]:
            best[r["aid"]] = {
                "asset_id": r["aid"], "name": r["name"],
                "atype": r["atype"], "state": r["state"],
                "seq": r["seq"], "blob": r["blob_hash"],
            }
    return sorted(best.values(), key=lambda x: (x["atype"], x["name"]))


def export_bundle(db_path, conversation_id=None, latest=False,
                  out_root=None):
    reg = Registry(db_path)
    db = reg.db
    nodes_mod.ensure_tables(reg)
    conv = None
    if latest or not conversation_id:
        conv = db.execute(
            "SELECT * FROM conversations ORDER BY created DESC LIMIT 1"
        ).fetchone()
    else:
        conv = db.execute(
            "SELECT * FROM conversations WHERE id=?", (conversation_id,)
        ).fetchone()
        if conv is None:
            conv = db.execute(
                "SELECT * FROM conversations WHERE id LIKE ? OR title LIKE ? "
                "ORDER BY created DESC LIMIT 1",
                (conversation_id + "%", "%" + conversation_id + "%"),
            ).fetchone()
    if conv is None:
        return {"error": "conversation_not_found"}
    items = _conversation_assets(db, conv["id"])
    stamp = time.strftime("%Y%m%d-%H%M")
    outdir = out_root or os.path.join(
        os.path.expanduser("~/LeanFile-Exports"),
        _slug(conv["title"]) + "-" + stamp,
    )
    os.makedirs(outdir, exist_ok=True)
    used, files, missing = set(), [], []
    for it in items:
        src = _src_path(db, it["blob"])
        if src is None:
            missing.append(it["name"])
            continue
        base = os.path.basename(src)
        stem, ext = os.path.splitext(base)
        name, n = base, 2
        while name in used:
            name = f"{stem} ({n}){ext}"
            n += 1
        used.add(name)
        dest = os.path.join(outdir, name)
        shutil.copy2(src, dest)
        files.append({
            "asset": it["name"], "file": name, "version_seq": it["seq"],
            "state": it["state"], "size": os.path.getsize(dest),
            "sha256": it["blob"],
        })
    manifest = {
        "conversation": {
            "id": conv["id"], "title": conv["title"],
            "tool": conv["tool"], "model": conv["model"],
            "inferred": bool(conv["inferred"]),
        },
        "exported_at": time.strftime("%Y-%m-%d %H:%M"),
        "files": files, "missing": missing,
    }
    with open(os.path.join(outdir, "bundle.json"), "w") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    lines = [
        f"# {conv['title'] or '对话打包'}",
        "",
        f"- 对话 conversation: {conv['id']}"
        + ("（推断归组）" if conv["inferred"] else "（实录）"),
        f"- 工具 tool: {conv['tool'] or '-'} / 模型 model: {conv['model'] or '-'}",
        f"- 导出时间 exported: {manifest['exported_at']}",
        f"- 文件 files: {len(files)} 个",
        "",
        "## 文件清单",
        "",
    ]
    for fi in files:
        lines.append(
            f"- {fi['file']} — {fi['asset']}（v{fi['version_seq']}，"
            f"{fi['state']}，{fi['size']} B）"
        )
    if missing:
        lines += ["", "## 缺失（源文件已不在磁盘上）", ""]
        lines += [f"- {m}" for m in missing]
    with open(os.path.join(outdir, "BUNDLE.md"), "w") as f:
        f.write("\n".join(lines) + "\n")
    return {
        "dir": outdir, "title": conv["title"], "count": len(files),
        "bytes": sum(f["size"] for f in files), "missing": missing,
    }


def protect_run(db_path, target_node=None, execute=False):
    """Copy at-risk protect-class assets to a second node (verified)."""
    reg = Registry(db_path)
    db = reg.db
    nodes_mod.ensure_tables(reg)
    node_list = nodes_mod.list_nodes(reg)
    if target_node is None:
        target_node = get_rules(db_path).get("protect_target") or None
    if target_node is None and node_list:
        target_node = node_list[-1]["name"]
    if target_node is None:
        return {"error": "no_nodes_registered"}
    target = nodes_mod.get_node(reg, target_node)
    if target is None:
        return {"error": "target_node_not_found", "target": target_node}
    plan0 = protect_plan(db_path)
    at_risk_names = set(plan0["at_risk"])
    rows = db.execute(
        "SELECT a.id, a.name, "
        "(SELECT blob_hash FROM versions v WHERE v.asset_id=a.id "
        " ORDER BY seq DESC LIMIT 1) AS blob "
        "FROM assets a WHERE a.importance='protect'"
    ).fetchall()
    planned, done, skipped = [], [], []
    for r in rows:
        if r["name"] not in at_risk_names or not r["blob"]:
            continue
        src = _src_path(db, r["blob"])
        if src is None:
            skipped.append({"asset": r["name"], "why": "source_missing"})
            continue
        on_target = db.execute(
            "SELECT COUNT(*) AS c FROM locations WHERE hash=? AND node=?",
            (r["blob"], target_node),
        ).fetchone()["c"]
        if on_target:
            continue
        dest = os.path.join(
            target["path"], "LeanFileVault", r["blob"][:2],
            r["blob"][:16] + "_" + os.path.basename(src),
        )
        item = {"asset": r["name"], "src": src, "dest": dest,
                "hash": r["blob"]}
        planned.append(item)
        if execute:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(src, dest)
            if hash_file(dest) != r["blob"]:
                os.remove(dest)
                raise IOError("hash mismatch after copy: " + dest)
            st = os.stat(dest)
            nodes_mod._record_location(
                reg, dest, r["blob"], target_node, st.st_size, st.st_mtime)
            db.execute(
                "INSERT OR IGNORE INTO blob_locations VALUES (?,?)",
                (r["blob"], os.path.abspath(dest)),
            )
            done.append(item)
    if execute:
        db.commit()
    return {
        "target": target_node, "protect_total": plan0["protect_total"],
        "planned": planned, "done": done, "skipped": skipped,
    }
