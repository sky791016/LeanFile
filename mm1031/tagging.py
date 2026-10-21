"""Auto-tagging and faceted organization.

Philosophy: users should not have to build folder trees. They drop
files anywhere; LeanFile tags every asset along several dimensions
(category, time, type, project, importance, extension, content
keywords) so any combination of tags becomes a view. A physical
folder tree is one optional output (see organize.py), never the
way you are forced to think.

Rule tags are computed locally, for free. Content tags read the
stored text excerpt through the compute chain: an endpoint model
when one is configured (costs tokens, recorded as an enrichment),
otherwise the T0 local keyword extractor.
"""

import os
import re
import sqlite3
import time
from collections import Counter

from .autopilot import classify_all
from .compute import ComputeError, build_chain, load_config

DIMS = ("category", "time", "type", "project", "importance", "ext",
        "content")

_EN_STOP = {
    "the", "and", "for", "with", "this", "that", "from", "are", "was",
    "were", "has", "have", "had", "not", "but", "all", "can", "her",
    "his", "its", "our", "you", "your", "they", "them", "then", "than",
    "into", "over", "such", "only", "also", "which", "when", "what",
}
_ZH_STOP = set("的了和与及或是在有无之于等为被把让从向对中内外上下这那个")


def ensure_tag_tables(db):
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS tags(
          asset_id TEXT, tag TEXT, dim TEXT, source TEXT,
          created REAL,
          PRIMARY KEY(asset_id, dim, tag));
        CREATE INDEX IF NOT EXISTS idx_tags_lookup
          ON tags(dim, tag, asset_id);
        """
    )
    db.commit()


def _asset_time(db, asset_id, fallback):
    row = db.execute(
        "SELECT MIN(l.mtime) FROM locations l "
        "JOIN versions v ON v.blob_hash=l.hash WHERE v.asset_id=?",
        (asset_id,),
    ).fetchone()
    return (row and row[0]) or fallback or time.time()


def _latest_excerpt(db, asset_id):
    row = db.execute(
        "SELECT p.excerpt, p.display_title FROM previews p "
        "WHERE p.hash=(SELECT blob_hash FROM versions "
        "WHERE asset_id=? ORDER BY seq DESC LIMIT 1)",
        (asset_id,),
    ).fetchone()
    if not row:
        return ""
    return (row[0] or "") or (row[1] or "")


def local_keywords(text, topn=5):
    """T0 keyword extraction: latin tokens + CJK bigrams by frequency."""
    tokens = [t for t in re.findall(r"[A-Za-z0-9_]{3,}", text.lower())
              if t not in _EN_STOP]
    chars = [c for c in re.findall(r"[一-鿿]", text or "")
             if c not in _ZH_STOP]
    bigrams = [chars[i] + chars[i + 1] for i in range(len(chars) - 1)]
    return [w for w, _ in Counter(tokens + bigrams).most_common(topn)]


def _parse_keywords(summary):
    m = re.search(r"关键词[:：]\s*(.+)$", summary or "", re.S)
    if not m:
        return []
    words = []
    for part in re.split(r"[\n、,，;；/]+", m.group(1)):
        p = part.strip().strip("*# ")
        p = re.sub(r"^\d+[.、)]\s*", "", p)
        p = re.sub(r"\*\*(.+?)\*\*", r"\1", p)
        p = re.split(r"[（(]", p)[0].strip().strip("* ")
        if 2 <= len(p) <= 12:
            words.append(p)
    return words[:5]


def rule_tags(db, row, path=""):
    out = []
    if row["category"]:
        out.append((row["category"], "category"))
    if row["importance"]:
        out.append((row["importance"], "importance"))
    if row["atype"]:
        out.append((row["atype"], "type"))
    if row["project"]:
        out.append((row["project"], "project"))
    ext = os.path.splitext(path or row["name"] or "")[1].lower()
    if ext:
        out.append((ext, "ext"))
    t = _asset_time(db, row["id"], row["created"])
    out.append((time.strftime("%Y-%m", time.localtime(t)), "time"))
    return out


def tag_all(db_path, content=False, config_path=None,
            refresh_content=False):
    """(Re)build tags for every asset. Returns run statistics."""
    # repair pass: assets registered before the type map grew keep a
    # stale atype; re-derive it from a real path so categories bite.
    from .core import guess_type

    db0 = sqlite3.connect(db_path)
    db0.execute("PRAGMA busy_timeout=30000")
    for aid, path in db0.execute(
        "SELECT v.asset_id, l.path FROM versions v "
        "JOIN locations l ON l.hash=v.blob_hash GROUP BY v.asset_id"
    ).fetchall():
        db0.execute(
            "UPDATE assets SET atype=? WHERE id=? AND (atype IS NULL "
            "OR atype='file')", (guess_type(path), aid),
        )
    db0.commit()
    db0.close()
    classify_all(db_path)
    db = sqlite3.connect(db_path)
    db.execute("PRAGMA busy_timeout=30000")
    db.row_factory = sqlite3.Row
    ensure_tag_tables(db)
    chain = None
    if content:
        chain = build_chain(load_config(config_path), "summarize")
    rows = db.execute(
        "SELECT id, name, atype, project, category, importance, created "
        "FROM assets"
    ).fetchall()
    stats = {"assets": 0, "rule_tags": 0, "content_tagged": 0,
             "content_skipped": 0}
    now = time.time()
    for row in rows:
        stats["assets"] += 1
        db.execute(
            "DELETE FROM tags WHERE asset_id=? AND source='rule'",
            (row["id"],),
        )
        rep = db.execute(
            "SELECT l.path FROM locations l "
            "JOIN versions v ON v.blob_hash=l.hash "
            "WHERE v.asset_id=? ORDER BY v.seq DESC LIMIT 1",
            (row["id"],),
        ).fetchone()
        for tag, dim in rule_tags(db, row, rep[0] if rep else ""):
            db.execute(
                "INSERT OR REPLACE INTO tags VALUES (?,?,?,?,?)",
                (row["id"], tag, dim, "rule", now),
            )
            stats["rule_tags"] += 1
        if not content:
            continue
        have = db.execute(
            "SELECT COUNT(*) FROM tags WHERE asset_id=? AND dim='content'",
            (row["id"],),
        ).fetchone()[0]
        if have and not refresh_content:
            stats["content_skipped"] += 1
            continue
        text = _latest_excerpt(db, row["id"])
        if not text:
            stats["content_skipped"] += 1
            continue
        words, provider, model, cost = [], "local-basic", "extractive-v1", 0
        if chain is not None:
            try:
                res = chain.tag_keywords(text)
                words = [w for w in re.split(r"[、,，\s]+", res.text)
                         if 2 <= len(w) <= 12][:5]
                provider, model, cost = res.provider, res.model, \
                    res.cost_units
            except ComputeError:
                words = []
            if not words:
                try:
                    res = chain.summarize(text)
                    words = _parse_keywords(res.text)
                    provider, model, cost = res.provider, res.model, \
                        res.cost_units
                except ComputeError:
                    words = []
        if not words:
            words = local_keywords(text)
            provider, model, cost = "local-basic", "extractive-v1", 0
        if not words:
            stats["content_skipped"] += 1
            continue
        db.execute(
            "DELETE FROM tags WHERE asset_id=? AND dim='content'",
            (row["id"],),
        )
        for w in words:
            db.execute(
                "INSERT OR REPLACE INTO tags VALUES (?,?,?,?,?)",
                (row["id"], w, "content", provider, now),
            )
        db.execute(
            "INSERT INTO enrichments(asset_id, feature, provider, model,"
            " cost_units, created) VALUES (?,?,?,?,?,?)",
            (row["id"], "content_tags", provider, model, cost, now),
        )
        stats["content_tagged"] += 1
        if stats["content_tagged"] % 25 == 0:
            db.commit()  # long content runs checkpoint as they go
    db.commit()
    db.close()
    return stats


def facets(db_path):
    """{dim: [(tag, asset_count), ...]} sorted by count desc."""
    db = sqlite3.connect(db_path)
    ensure_tag_tables(db)
    out = {}
    for dim, tag, n in db.execute(
        "SELECT dim, tag, COUNT(DISTINCT asset_id) FROM tags "
        "GROUP BY dim, tag ORDER BY dim, COUNT(DISTINCT asset_id) DESC, "
        "tag"
    ):
        out.setdefault(dim, []).append((tag, n))
    db.close()
    return out


def filter_assets(db_path, wanted):
    """Asset ids matching ALL dimensions (OR within one dimension).

    wanted: {dim: [tag, ...]} — the combination rule: pick a category
    AND a month AND a content keyword, get exactly that intersection.
    """
    db = sqlite3.connect(db_path)
    ensure_tag_tables(db)
    result = None
    for dim, tags in (wanted or {}).items():
        if not tags:
            continue
        marks = ",".join("?" * len(tags))
        ids = {
            r[0]
            for r in db.execute(
                f"SELECT asset_id FROM tags WHERE dim=? AND tag IN "
                f"({marks})",
                (dim, *tags),
            )
        }
        result = ids if result is None else result & ids
        if not result:
            break
    db.close()
    return sorted(result or [])
