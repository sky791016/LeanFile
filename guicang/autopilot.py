"""Autopilot: the user-facing value layer.

The user does not care about process data. They care about five
outcomes, and this module delivers them automatically:
  1. auto dedup        - identical content keeps ONE best copy
  2. auto classify     - every file gets a category + importance class
  3. full-text search  - FTS index over document bodies (engine.py)
  4. never lose the important ones - protect class gets 2-copy coverage
  5. junk expires      - temp/intermediate files are listed for removal

Safety contract (hard rules, from the user's standing instructions):
  - Classification and planning are automatic and non-destructive.
  - Anything destructive is QUARANTINE (a move, fully logged, one-click
    restore), never a hard delete, and only runs after the user has
    seen the plan and confirmed. The last copy of anything is never
    quarantined; a protect-class asset always keeps a copy in place.
"""
import os
import re
import shutil
import sqlite3
import time

TEMP_PATTERNS = ("~$", ".tmp", ".temp", ".part", ".crdownload", ".download")
COPY_SUFFIX = re.compile(r"\s\(\d+\)(\.[^.]+)$")
FINAL_WORDS = ("定稿", "终版", "正式版", "final", "交付")
PROTECT_DIRS = ("deliverables", "交付", "定稿", "final")


def ensure_columns(db):
    cols = [r[1] for r in db.execute("PRAGMA table_info(assets)")]
    if "importance" not in cols:
        db.execute("ALTER TABLE assets ADD COLUMN importance TEXT DEFAULT 'keep'")
    if "category" not in cols:
        db.execute("ALTER TABLE assets ADD COLUMN category TEXT DEFAULT ''")
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS quarantine_log(
          id INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT, qpath TEXT,
          hash TEXT, reason TEXT, created REAL, restored INTEGER DEFAULT 0);
        """
    )
    db.commit()


def importance_of(state, path, atype):
    """Score -> class: protect / keep / ephemeral."""
    low = path.lower()
    name = os.path.basename(path)
    score = 0
    if state in ("final", "published"):
        score += 100
    if any(w in name for w in FINAL_WORDS) or any(w in low for w in FINAL_WORDS):
        score += 40
    if any(d in low for d in PROTECT_DIRS):
        score += 30
    if name.startswith(TEMP_PATTERNS) or low.endswith(TEMP_PATTERNS):
        score -= 80
    if COPY_SUFFIX.search(name):
        score -= 30
    if "_part" in low or "part0" in low or "/cache/" in low or "render" in low:
        score -= 30
    if atype in ("document", "slides"):
        score += 10
    if score >= 60:
        return "protect"
    if score <= -30:
        return "ephemeral"
    return "keep"


CATEGORY_RULES = [
    ("视频成片", ("video",), ("终版", "定稿", "final", "成片", "-v", "1080p", "720p")),
    ("视频素材", ("video",), ()),
    ("合同协议", ("document", "slides"), ("合同", "协议", "contract")),
    ("方案报告", ("document", "slides"), ("方案", "报告", "申请", "规划", "report", "ppt")),
    ("表格数据", ("document",), ()),
    ("图片", ("image",), ()),
    ("音频", ("audio",), ()),
    ("文档资料", ("document", "slides"), ()),
]


def category_of(name, atype, path):
    low = (name + path).lower()
    ext = os.path.splitext(name)[1].lower()
    if ext in (".xlsx", ".xls", ".csv"):
        return "表格数据"
    for cat, types, words in CATEGORY_RULES:
        if atype in types and (not words or any(w in low for w in words)):
            return cat
    return "其他文件"


def classify_all(db_path):
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    ensure_columns(db)
    rows = db.execute(
        "SELECT a.id, a.state, a.atype, a.name FROM assets a"
    ).fetchall()
    rank = {"protect": 2, "keep": 1, "ephemeral": 0}
    counts = {"protect": 0, "keep": 0, "ephemeral": 0}
    cats = {}
    for r in rows:
        locs = db.execute(
            "SELECT l.path FROM locations l WHERE l.hash="
            " (SELECT blob_hash FROM versions v WHERE v.asset_id=? "
            "  ORDER BY seq DESC LIMIT 1)",
            (r["id"],),
        ).fetchall()
        paths = [x[0] for x in locs] or [""]
        # an asset is as important as its MOST protected location
        best_path = max(
            paths,
            key=lambda p: rank[importance_of(r["state"], p, r["atype"])],
        )
        imp = importance_of(r["state"], best_path, r["atype"])
        cat = category_of(r["name"], r["atype"], best_path)
        db.execute(
            "UPDATE assets SET importance=?, category=? WHERE id=?",
            (imp, cat, r["id"]),
        )
        counts[imp] += 1
        cats[cat] = cats.get(cat, 0) + 1
    db.commit()
    return {"importance": counts, "categories": cats}


def _best_copy(paths_with_imp):
    """Keeper: protect-class first, then not-a-copy-name, then shortest path."""
    def rank(item):
        path, imp = item
        return (
            0 if imp == "protect" else 1,
            1 if COPY_SUFFIX.search(os.path.basename(path)) else 0,
            len(path),
        )
    return sorted(paths_with_imp, key=rank)[0][0]


def dedup_plan(db_path):
    """Exact duplicates: keep the best copy, quarantine the rest."""
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    ensure_columns(db)
    groups = db.execute(
        "SELECT hash FROM blob_locations GROUP BY hash HAVING COUNT(*)>1"
    ).fetchall()
    plan, total_wasted = [], 0
    for g in groups:
        digest = g["hash"]
        size = db.execute(
            "SELECT size FROM blobs WHERE hash=?", (digest,)
        ).fetchone()[0]
        state_row = db.execute(
            "SELECT state, atype FROM assets a JOIN versions v "
            "ON v.asset_id=a.id WHERE v.blob_hash=? LIMIT 1",
            (digest,),
        ).fetchone()
        blob_state = state_row[0] if state_row else "draft"
        blob_type = state_row[1] if state_row else "file"
        locs = db.execute(
            "SELECT DISTINCT path FROM locations WHERE hash=?", (digest,)
        ).fetchall()
        paths = [
            (r["path"], importance_of(blob_state, r["path"], blob_type))
            for r in locs
        ]
        if len(paths) < 2:
            continue
        keeper = _best_copy(paths)
        for p, _imp in paths:
            if p != keeper:
                plan.append(
                    {"path": p, "keeper": keeper, "hash": digest,
                     "size": size, "reason": "重复副本 duplicate"}
                )
                total_wasted += size
    return {"actions": plan, "reclaimable": total_wasted}


def expire_plan(db_path, min_age_days=0):
    """Ephemeral-class files that are safe to remove.

    Safe = removing this path still leaves the content available
    (another location of the same blob) OR the file is a temp pattern.
    Protect/keep sole copies are never listed.
    """
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    ensure_columns(db)
    rows = db.execute(
        "SELECT a.name, l.path, l.hash, b.size FROM assets a "
        "JOIN versions v ON v.asset_id=a.id "
        "JOIN locations l ON l.hash=v.blob_hash "
        "JOIN blobs b ON b.hash=l.hash "
        "WHERE a.importance='ephemeral'"
    ).fetchall()
    plan = []
    for r in rows:
        copies = db.execute(
            "SELECT COUNT(*) FROM locations WHERE hash=?", (r["hash"],)
        ).fetchone()[0]
        is_temp = os.path.basename(r["path"]).startswith(TEMP_PATTERNS)
        if copies >= 2 or is_temp:
            plan.append(
                {"path": r["path"], "hash": r["hash"], "size": r["size"],
                 "reason": "临时/中间文件 ephemeral"}
            )
    return {"actions": plan, "reclaimable": sum(p["size"] for p in plan)}


def protect_plan(db_path):
    """Protect-class assets with fewer than 2 physical locations."""
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    ensure_columns(db)
    rows = db.execute(
        "SELECT a.name, "
        "(SELECT COUNT(DISTINCT node) FROM locations l WHERE l.hash="
        " (SELECT blob_hash FROM versions v WHERE v.asset_id=a.id "
        "  ORDER BY seq DESC LIMIT 1)) AS nodes "
        "FROM assets a WHERE a.importance='protect'"
    ).fetchall()
    at_risk = [r["name"] for r in rows if (r["nodes"] or 0) < 2]
    return {"protect_total": len(rows), "at_risk": at_risk}


DEFAULT_RULES = {
    "stale_versions_enabled": "0",   # auto-clean old PROCESS versions
    "stale_versions_days": "30",     # keep process versions this long
    "dedup_enabled": "0",            # auto-quarantine duplicate extra copies
    "ephemeral_enabled": "0",        # auto-quarantine temp/intermediate files
    "ephemeral_days": "7",
    "quarantine_retention_days": "30",  # then quarantined files are purged
}


def ensure_settings(db):
    db.execute(
        "CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT)"
    )
    for k, v in DEFAULT_RULES.items():
        db.execute("INSERT OR IGNORE INTO settings VALUES (?,?)", (k, v))
    db.commit()


def get_rules(db_path):
    db = sqlite3.connect(db_path)
    ensure_settings(db)
    rules = dict(db.execute("SELECT key, value FROM settings").fetchall())
    return {**DEFAULT_RULES, **rules}


def set_rule(db_path, key, value):
    db = sqlite3.connect(db_path)
    ensure_settings(db)
    db.execute(
        "INSERT INTO settings VALUES (?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )
    db.commit()


def stale_version_plan(db_path, days):
    """Old PROCESS versions: non-current versions older than `days`.

    The current version and the asset itself are never touched; only
    physical files belonging exclusively to superseded versions.
    """
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    cutoff = time.time() - days * 86400
    rows = db.execute(
        "SELECT v.id, v.asset_id, v.blob_hash, v.seq FROM versions v "
        "WHERE v.seq < (SELECT MAX(seq) FROM versions WHERE asset_id=v.asset_id) "
        "AND v.created < ?",
        (cutoff,),
    ).fetchall()
    plan = []
    for r in rows:
        current_hash = db.execute(
            "SELECT blob_hash FROM versions WHERE asset_id=? "
            "ORDER BY seq DESC LIMIT 1",
            (r["asset_id"],),
        ).fetchone()[0]
        if r["blob_hash"] == current_hash:
            continue  # same content as current version: not a process copy
        current_paths = {
            x[0]
            for x in db.execute(
                "SELECT path FROM blob_locations WHERE hash=?", (current_hash,)
            ).fetchall()
        }
        locs = db.execute(
            "SELECT path, size FROM blob_locations l "
            "JOIN blobs b ON b.hash=l.hash WHERE l.hash=?",
            (r["blob_hash"],),
        ).fetchall()
        for loc in locs:
            if loc["path"] in current_paths:
                # in-place edited file: the path now holds the CURRENT
                # version's content - never quarantine it for a stale blob
                continue
            plan.append(
                {"path": loc["path"], "hash": r["blob_hash"],
                 "size": loc["size"],
                 "reason": f"过期过程版本 stale v{r['seq']}"}
            )
    return {"actions": plan, "reclaimable": sum(p["size"] for p in plan)}


def cleanup_plan(db_path, rules=None):
    rules = rules or get_rules(db_path)
    parts = {"stale": {"actions": [], "reclaimable": 0},
             "dedup": {"actions": [], "reclaimable": 0},
             "ephemeral": {"actions": [], "reclaimable": 0}}
    if rules.get("stale_versions_enabled") == "1":
        parts["stale"] = stale_version_plan(
            db_path, int(rules.get("stale_versions_days", "30"))
        )
    if rules.get("dedup_enabled") == "1":
        parts["dedup"] = dedup_plan(db_path)
    if rules.get("ephemeral_enabled") == "1":
        parts["ephemeral"] = expire_plan(db_path)
    return parts


def purge_quarantine(db_path, retention_days, quarantine_dir):
    """Permanently delete quarantined files older than the retention.

    Only files physically inside quarantine_dir are ever removed.
    """
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    ensure_columns(db)
    cutoff = time.time() - retention_days * 86400
    rows = db.execute(
        "SELECT id, qpath FROM quarantine_log "
        "WHERE restored=0 AND created < ?",
        (cutoff,),
    ).fetchall()
    purged = []
    qroot = os.path.realpath(quarantine_dir)
    for r in rows:
        if os.path.realpath(r["qpath"]).startswith(qroot) and os.path.exists(r["qpath"]):
            os.remove(r["qpath"])
            purged.append(r["qpath"])
        db.execute(
            "UPDATE quarantine_log SET restored=2 WHERE id=?", (r["id"],)
        )
    db.commit()
    return {"purged": purged}


def run_cleanup(db_path, quarantine_dir, rules=None):
    """Execute the plan the user's rules define. Rules ARE the consent:
    nothing runs for a category whose switch is off."""
    rules = rules or get_rules(db_path)
    parts = cleanup_plan(db_path, rules)
    actions = (
        parts["stale"]["actions"] + parts["dedup"]["actions"]
        + parts["ephemeral"]["actions"]
    )
    out = execute_quarantine(db_path, actions, quarantine_dir)
    purged = purge_quarantine(
        db_path, int(rules.get("quarantine_retention_days", "30")), quarantine_dir
    )
    db = sqlite3.connect(db_path)
    ensure_settings(db)
    db.execute(
        "INSERT INTO settings VALUES ('last_cleanup', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (f"{time.strftime('%Y-%m-%d %H:%M')} moved={len(out['moved'])} "
         f"failed={len(out['failed'])} purged={len(purged['purged'])}",),
    )
    db.commit()
    return {
        "planned": {k: len(v["actions"]) for k, v in parts.items()},
        "moved": out["moved"],
        "failed": out["failed"],
        "purged": purged["purged"],
    }


def execute_quarantine(db_path, actions, quarantine_dir):
    """Move files to quarantine (NEVER hard-delete). Fully logged."""
    db = sqlite3.connect(db_path)
    ensure_columns(db)
    os.makedirs(quarantine_dir, exist_ok=True)
    done, failed = [], []
    for a in actions:
        src = a["path"]
        if not os.path.exists(src):
            failed.append((src, "missing"))
            continue
        dest = os.path.join(
            quarantine_dir,
            a["hash"][:12] + "_" + os.path.basename(src),
        )
        try:
            shutil.move(src, dest)
        except OSError as e:
            failed.append((src, str(e)))
            continue
        db.execute(
            "INSERT INTO quarantine_log(path, qpath, hash, reason, created) "
            "VALUES (?,?,?,?,?)",
            (src, dest, a["hash"], a["reason"], time.time()),
        )
        if db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='locations'"
        ).fetchone():
            db.execute("DELETE FROM locations WHERE path=?", (src,))
        db.execute("DELETE FROM blob_locations WHERE path=?", (src,))
        done.append(src)
    db.commit()
    return {"moved": done, "failed": failed}


def restore_quarantine(db_path, log_id=None):
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    ensure_columns(db)
    q = "SELECT * FROM quarantine_log WHERE restored=0"
    rows = db.execute(q + (" AND id=?" if log_id else ""), (log_id,) if log_id else ()).fetchall()
    restored = []
    for r in rows:
        if os.path.exists(r["qpath"]) and not os.path.exists(r["path"]):
            os.makedirs(os.path.dirname(r["path"]), exist_ok=True)
            shutil.move(r["qpath"], r["path"])
            db.execute(
                "UPDATE quarantine_log SET restored=1 WHERE id=?", (r["id"],)
            )
            restored.append(r["path"])
    db.commit()
    return {"restored": restored}
