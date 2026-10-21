"""Previews + conversation linkage: make assets human-readable.

Two readability problems this solves:
1. No preview: a list of filenames tells a human nothing. Every asset
   gets a preview record: a Quick Look thumbnail (macOS) and/or a
   text excerpt, plus a readable display title when the filename is
   machine gibberish (hashes, uuids, dispatcher names).
2. No context: an asset must hang off the conversation that produced
   it. Conversations are first-class rows; provenance links versions
   to them. For legacy scanned files we infer production batches
   (same tool prefix + folder + time window) and mark them inferred -
   never presented as fact.
"""
import os
import re
import sqlite3
import subprocess
import time
import uuid
import zipfile

GIBBERISH = re.compile(
    r"([0-9a-f]{8,}-[0-9a-f-]{12,}|[0-9a-f]{24,}|-dispatcher-|-longloop-|-gpu-)",
    re.IGNORECASE,
)


def ensure_tables(db):
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS previews(
          hash TEXT PRIMARY KEY, kind TEXT, thumb_path TEXT,
          excerpt TEXT, display_title TEXT);
        CREATE TABLE IF NOT EXISTS conversations(
          id TEXT PRIMARY KEY, tool TEXT, model TEXT, title TEXT,
          inferred INTEGER, created REAL);
        """
    )
    cols = [r[1] for r in db.execute("PRAGMA table_info(provenance)")]
    if "conversation_id" not in cols:
        db.execute("ALTER TABLE provenance ADD COLUMN conversation_id TEXT")
    db.commit()


def readable_title(name, path):
    """Human title for a file; gibberish names fall back to folder+type."""
    stem = os.path.splitext(name)[0]
    if GIBBERISH.search(stem) or len(stem) > 60:
        parent = os.path.basename(os.path.dirname(path))
        ext = os.path.splitext(name)[1].lstrip(".").upper() or "文件"
        return f"{parent} · {ext} 产物"
    return stem


def text_excerpt(path, limit=420):
    low = path.lower()
    try:
        if low.endswith((".md", ".txt")):
            with open(path, encoding="utf-8", errors="replace") as f:
                body = f.read(4000)
        elif low.endswith(".docx"):
            with zipfile.ZipFile(path) as z:
                xml = z.read("word/document.xml").decode("utf-8", "replace")
            body = re.sub(r"<[^>]+>", " ", xml)
        else:
            return ""
    except Exception:
        return ""
    body = re.sub(r"\s+", " ", body).strip()
    return body[:limit]


def ql_thumbnail(path, outdir, size=640):
    """macOS Quick Look thumbnail; returns png path or ''."""
    os.makedirs(outdir, exist_ok=True)
    if os.path.basename(path).startswith(("~$", ".")):
        return ""  # Office lock files & hidden files hang Quick Look; skip
    try:
        subprocess.run(
            ["qlmanage", "-t", "-s", str(size), "-o", outdir, path],
            capture_output=True, timeout=12,
        )
    except Exception:
        return ""
    cand = os.path.join(outdir, os.path.basename(path) + ".png")
    return cand if os.path.exists(cand) else ""


def build_previews(db_path, cache_dir, use_ql=True):
    db = sqlite3.connect(db_path, timeout=30)
    db.row_factory = sqlite3.Row
    ensure_tables(db)
    path_of = {}
    for digest, path in db.execute("SELECT hash, path FROM locations"):
        path_of.setdefault(digest, path)
    assets = db.execute(
        "SELECT DISTINCT a.name, v.blob_hash AS hash FROM assets a "
        "JOIN versions v ON v.asset_id=a.id"
    ).fetchall()
    stats = {"assets": 0, "thumbs": 0, "excerpts": 0, "titles": 0}
    seen = set()
    for row in assets:
        digest = row["hash"]
        if digest in seen:
            continue
        seen.add(digest)
        path = path_of.get(digest)
        if not path:
            continue
        stats["assets"] += 1
        name = os.path.basename(path)
        title = readable_title(name, path)
        if title != os.path.splitext(name)[0]:
            stats["titles"] += 1
        excerpt = text_excerpt(path)
        if excerpt:
            stats["excerpts"] += 1
        thumb = ""
        low = path.lower()
        if use_ql and low.endswith(
            (".png", ".jpg", ".jpeg", ".webp", ".heic", ".mp4", ".mov",
             ".pdf", ".pptx", ".key", ".docx")
        ):
            thumb = ql_thumbnail(path, os.path.join(cache_dir, "thumbs"))
            if thumb:
                stats["thumbs"] += 1
        kind = "thumb" if thumb else ("text" if excerpt else "none")
        db.execute(
            "INSERT OR REPLACE INTO previews VALUES (?,?,?,?,?)",
            (digest, kind, thumb, excerpt, title),
        )
        if stats["assets"] % 100 == 0:
            # Commit in slices: holding one write transaction for a
            # whole-library rebuild would lock every other writer
            # (watcher scans, the app) out for minutes.
            db.commit()
    db.commit()
    return stats


SESSION_GAP_SECONDS = 3 * 3600  # silence longer than this = new session


def infer_conversation_batches(db_path):
    """Reconstruct conversations for legacy scanned files.

    A conversation is approximated as: same folder + one continuous
    work session (files whose mtimes chain within SESSION_GAP).
    Tool guessed from filename prefixes. Marked inferred=1 - a
    reconstruction, never presented as a recorded fact.
    """
    db = sqlite3.connect(db_path, timeout=30)
    db.row_factory = sqlite3.Row
    ensure_tables(db)
    rows = db.execute(
        "SELECT v.id AS vid, MIN(l.path) AS path, MIN(l.mtime) AS mt "
        "FROM versions v JOIN locations l ON l.hash=v.blob_hash "
        "LEFT JOIN provenance p ON p.version_id=v.id "
        "WHERE COALESCE(p.conversation_id,'')='' "
        "GROUP BY v.id"
    ).fetchall()
    by_parent = {}
    for r in rows:
        # a work session spans subfolders: group by the project-level
        # folder (two levels up), then split by time windows
        parent = os.path.dirname(os.path.dirname(r["path"]))
        by_parent.setdefault(parent, []).append((r["mt"] or 0, r["vid"], r["path"]))
    made = 0
    linked = 0
    for parent, items in by_parent.items():
        items.sort()
        windows = []
        cur = [items[0]]
        for prev, nxt in zip(items, items[1:]):
            if nxt[0] - prev[0] <= SESSION_GAP_SECONDS:
                cur.append(nxt)
            else:
                windows.append(cur)
                cur = [nxt]
        windows.append(cur)
        folder = os.path.basename(parent) or parent
        for win in windows:
            if len(win) < 2:
                continue
            sample = os.path.basename(win[0][2])
            tool = "Muse 媒体生成管线" if sample.startswith("media-generation") else ""
            day = time.strftime("%m月%d日", time.localtime(win[0][0])) if win[0][0] else ""
            title = f"{folder} · 同一批生成的文件"
            if day:
                title += f" · {day}"
            cid = uuid.uuid4().hex[:12]
            db.execute(
                "INSERT INTO conversations VALUES (?,?,?,?,1,?)",
                (cid, tool, "", title, win[0][0] or time.time()),
            )
            for _mt, v, _p in win:
                existing = db.execute(
                    "SELECT version_id FROM provenance WHERE version_id=?", (v,)
                ).fetchone()
                if existing:
                    db.execute(
                        "UPDATE provenance SET conversation_id=?, "
                        "tool=CASE WHEN tool='' THEN ? ELSE tool END "
                        "WHERE version_id=?",
                        (cid, tool, v),
                    )
                else:
                    db.execute(
                        "INSERT INTO provenance(version_id, tool, model, prompt, "
                        "prompt_hash, inputs, params, intent, conversation_id) "
                        "VALUES (?,?,?,?,?,?,?,?,?)",
                        (v, tool, "", "", "", "[]", "{}", "", cid),
                    )
                linked += 1
            made += 1
    db.commit()
    return {"batches": made, "versions_linked": linked}


def conversation_tree(db_path):
    """Conversations with their files: the conversation-first view."""
    db = sqlite3.connect(db_path, timeout=30)
    db.row_factory = sqlite3.Row
    ensure_tables(db)
    convs = db.execute(
        "SELECT c.*, COUNT(DISTINCT v.asset_id) AS files, "
        "COALESCE(SUM(b.size),0) AS bytes FROM conversations c "
        "LEFT JOIN provenance p ON p.conversation_id=c.id "
        "LEFT JOIN versions v ON v.id=p.version_id "
        "LEFT JOIN blobs b ON b.hash=v.blob_hash "
        "GROUP BY c.id ORDER BY c.created DESC"
    ).fetchall()
    out = []
    for c in convs:
        files = db.execute(
            "SELECT DISTINCT a.name, a.atype, a.state FROM provenance p "
            "JOIN versions v ON v.id=p.version_id "
            "JOIN assets a ON a.id=v.asset_id "
            "WHERE p.conversation_id=? ORDER BY a.atype, a.name",
            (c["id"],),
        ).fetchall()
        out.append(
            {
                "id": c["id"],
                "title": c["title"] or "(未命名对话)",
                "tool": c["tool"],
                "model": c["model"],
                "inferred": bool(c["inferred"]),
                "files": c["files"],
                "bytes": c["bytes"],
                "items": [dict(f) for f in files],
            }
        )
    return out
