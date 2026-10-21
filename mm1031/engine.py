"""Core engine: the part that must survive AI-era production scale.

Two jobs, in order of importance:
1. INGEST at scale - parallel hashing, one bulk transaction, WAL,
   incremental skip. A folder of 30k fragments must not take minutes
   of single-threaded work or a commit per file.
2. DE-FRAGMENT - turn the fragment flood back into whole assets:
   exact copies by hash, near-variants by content fingerprint
   (simhash clustering), shards by naming/structure patterns.
Everything else in Guicang is downstream of these two.
"""
import hashlib
import json
import os
import re
import sqlite3
import time
import uuid
from concurrent.futures import ProcessPoolExecutor

from .core import guess_type
from .nodes import SKIP_DIRS, ensure_tables


def _hash_job(job):
    path, size, mtime = job
    h = hashlib.blake2b(digest_size=32)
    try:
        with open(path, "rb") as f:
            while True:
                data = f.read(1 << 20)
                if not data:
                    break
                h.update(data)
        return (path, size, mtime, h.hexdigest(), "")
    except OSError as e:
        return (path, size, mtime, "", str(e))


def parallel_ingest(db_path, root, node, workers=None):
    """Walk root, hash in parallel, write in one bulk transaction."""
    from .core import Registry

    reg = Registry(db_path)
    ensure_tables(reg)
    reg.db.execute("PRAGMA journal_mode=WAL")
    root = os.path.abspath(root)
    jobs, skipped = [], 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            full = os.path.join(dirpath, fn)
            try:
                st = os.stat(full)
            except OSError:
                continue
            prev = reg.db.execute(
                "SELECT size, mtime FROM locations WHERE path=?", (full,)
            ).fetchone()
            if prev and prev[0] == st.st_size and abs(prev[1] - st.st_mtime) < 1:
                skipped += 1
                continue
            jobs.append((full, st.st_size, st.st_mtime))
    t0 = time.time()
    results = []
    if jobs:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            results = list(ex.map(_hash_job, jobs, chunksize=256))
    hash_s = time.time() - t0
    errors = [r for r in results if r[4]]
    ok = [r for r in results if not r[4]]
    t1 = time.time()
    cur = reg.db.cursor()
    cur.executemany(
        "INSERT OR IGNORE INTO blobs VALUES (?,?, 'blake2b-256')",
        [(r[3], r[1]) for r in ok],
    )
    cur.executemany(
        "INSERT OR IGNORE INTO blob_locations VALUES (?,?)",
        [(r[3], r[0]) for r in ok],
    )
    cur.executemany(
        "INSERT OR REPLACE INTO locations VALUES (?,?,?,?,?)",
        [(r[0], r[3], node, r[1], r[2]) for r in ok],
    )
    now = time.time()
    prepared = []
    for r in ok:
        rel = os.path.relpath(r[0], root)
        akey = f"scan::{node}::{rel}"
        stem = os.path.splitext(os.path.basename(r[0]))[0]
        prepared.append((akey, stem, guess_type(r[0]), r[3]))
    cur.executemany(
        "INSERT OR IGNORE INTO assets VALUES (?,?,?,?,?,?,1,?)",
        [
            (uuid.uuid4().hex[:12], akey, stem, "节点扫描/" + node, atype, "draft", now)
            for akey, stem, atype, _ in prepared
        ],
    )
    id_map = {
        row[0]: row[1]
        for row in cur.execute(
            "SELECT akey, id FROM assets WHERE akey LIKE ?", (f"scan::{node}::%",)
        ).fetchall()
    }
    seq_map = {
        row[0]: row[1]
        for row in cur.execute(
            "SELECT asset_id, COALESCE(MAX(seq),0) FROM versions GROUP BY asset_id"
        ).fetchall()
    }
    version_rows = []
    for akey, _stem, _atype, digest in prepared:
        aid = id_map[akey]
        seq = seq_map.get(aid, 0) + 1
        seq_map[aid] = seq
        version_rows.append(
            (uuid.uuid4().hex[:12], aid, seq, digest, "", "scan", now)
        )
    cur.executemany(
        "INSERT INTO versions VALUES (?,?,?,?,?,?,?)", version_rows
    )
    reg.db.commit()
    write_s = time.time() - t1
    return {
        "seen_new": len(jobs),
        "skipped_unchanged": skipped,
        "ingested": len(ok),
        "errors": len(errors),
        "hash_seconds": round(hash_s, 2),
        "write_seconds": round(write_s, 2),
    }


# ---------- de-fragmentation ----------

_PACK_CACHE = {}


def _packed_token(tok):
    """Per-token bit counts packed into 8-bit fields of one big int (SWAR).

    Lets a whole document's simhash weights be computed with ~130 big-int
    additions in C instead of 130x64 Python loop steps. Cached per token:
    real corpora reuse a small vocabulary across millions of fragments.
    """
    packed = _PACK_CACHE.get(tok)
    if packed is None:
        v = int.from_bytes(
            hashlib.blake2b(tok.encode(), digest_size=8).digest(), "big"
        )
        packed = 0
        bit = 0
        while v:
            if v & 1:
                packed += 1 << (8 * bit)
            v >>= 1
            bit += 1
        _PACK_CACHE[tok] = packed
    return packed


def _tokens(text):
    tokens = re.findall(r"[A-Za-z0-9_]+", text.lower())
    chars = re.findall(r"[一-鿿]", text)
    tokens += [chars[i] + chars[i + 1] for i in range(len(chars) - 1)]
    return tokens


def simhash64(text):
    uniq = set(_tokens(text))
    if not uniq or len(uniq) > 250:
        # field overflow guard for very long documents: sample deterministically
        uniq = set(sorted(uniq)[:250])
    total = 0
    for tok in uniq:
        total += _packed_token(tok)
    n = len(uniq)
    out = 0
    for bit in range(64):
        if ((total >> (8 * bit)) & 0xFF) * 2 > n:
            out |= 1 << bit
    return out


def _hamming(a, b):
    return bin(a ^ b).count("1")


class _UF:
    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb


def ensure_frag_tables(db):
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS fingerprints(
          hash TEXT PRIMARY KEY, simhash INTEGER);
        CREATE TABLE IF NOT EXISTS frag_clusters(
          cluster_id TEXT, method TEXT, member_hash TEXT, extra TEXT);
        """
    )
    db.commit()


def cluster_text_variants(db, max_bytes=300_000, threshold=8):
    """Cluster near-duplicate text blobs by simhash (banding + union-find)."""
    ensure_frag_tables(db)
    rows = db.execute(
        "SELECT b.hash, b.size FROM blobs b WHERE b.size<=?", (max_bytes,)
    ).fetchall()
    path_of = {}
    for digest, path in db.execute(
        "SELECT hash, path FROM locations"
    ).fetchall():
        path_of.setdefault(digest, path)
    fps = {}
    token_sets = {}
    for digest, _size in rows:
        path = path_of.get(digest)
        if path is None:
            continue
        if not path.lower().endswith((".md", ".txt")):
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        fps[digest] = simhash64(text)
        token_sets[digest] = set(_tokens(text))
    def _signed(v):
        return v - (1 << 64) if v >= (1 << 63) else v

    db.executemany(
        "INSERT OR REPLACE INTO fingerprints VALUES (?,?)",
        [(h, _signed(v)) for h, v in fps.items()],
    )
    # banding: 8 bands x 8 bits; sharing any band makes a candidate pair.
    # (4x16 bands missed most pairs at hamming 8-12: a band survives only
    # if all its 16 bits match. 8x8 raises candidate recall sharply.)
    buckets = {}
    for digest, fp in fps.items():
        for band in range(8):
            key = (band, (fp >> (band * 8)) & 0xFF)
            buckets.setdefault(key, []).append(digest)
    uf = _UF()
    pairs = 0
    for members in buckets.values():
        if len(members) > 400:
            continue  # mega-bucket: low-information band value, skip
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                a, b = members[i], members[j]
                if uf.find(a) == uf.find(b):
                    continue
                d = _hamming(fps[a], fps[b])
                if d <= threshold:
                    uf.union(a, b)
                    pairs += 1
                elif d <= 20:
                    # borderline: fingerprint proposes, real similarity decides
                    sa, sb = token_sets.get(a, set()), token_sets.get(b, set())
                    union_n = len(sa | sb)
                    if union_n and len(sa & sb) / union_n >= 0.8:
                        uf.union(a, b)
                        pairs += 1
    groups = {}
    for digest in fps:
        groups.setdefault(uf.find(digest), []).append(digest)
    clusters = [g for g in groups.values() if len(g) >= 2]
    db.execute("DELETE FROM frag_clusters WHERE method='simhash'")
    for g in clusters:
        cid = uuid.uuid4().hex[:10]
        db.executemany(
            "INSERT INTO frag_clusters VALUES (?,?,?,?)",
            [(cid, "simhash", h, "") for h in g],
        )
    db.commit()
    return {"fingerprinted": len(fps), "candidate_pairs": pairs, "clusters": clusters}


def build_content_index(db, max_bytes=300_000):
    """Full-text index (FTS5) over extracted text of document blobs.

    Extraction here handles .md/.txt directly; on macOS the native
    helper additionally uses PDFKit/textutil/Spotlight importers.
    """
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS content_text(
          hash TEXT PRIMARY KEY, body TEXT);
        CREATE VIRTUAL TABLE IF NOT EXISTS content_fts
          USING fts5(hash UNINDEXED, body);
        """
    )
    path_of = {}
    for digest, path in db.execute("SELECT hash, path FROM locations"):
        path_of.setdefault(digest, path)
    done = {r[0] for r in db.execute("SELECT hash FROM content_text")}
    rows = []
    for digest, _size in db.execute(
        "SELECT hash, size FROM blobs WHERE size<=?", (max_bytes,)
    ).fetchall():
        if digest in done:
            continue
        path = path_of.get(digest)
        if not path or not path.lower().endswith((".md", ".txt")):
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                body = f.read()
        except OSError:
            continue
        rows.append((digest, body))
    db.executemany("INSERT OR REPLACE INTO content_text VALUES (?,?)", rows)
    db.execute("DELETE FROM content_fts")
    db.execute(
        "INSERT INTO content_fts(hash, body) SELECT hash, body FROM content_text"
    )
    db.commit()
    return {"indexed": len(rows)}


def search_content(db, query, limit=20):
    """Ranked full-text search; returns (hash, rank, example_path)."""
    rows = db.execute(
        "SELECT hash, rank FROM content_fts WHERE content_fts MATCH ? "
        "ORDER BY rank LIMIT ?",
        (query, limit),
    ).fetchall()
    out = []
    for digest, rank in rows:
        p = db.execute(
            "SELECT path FROM locations WHERE hash=? LIMIT 1", (digest,)
        ).fetchone()
        out.append(
            {"hash": digest[:12], "rank": rank, "path": p[0] if p else ""}
        )
    return out


_SHARD_TAIL = re.compile(
    r"([\-_\s]*\(?\d{1,4}\)?$|[\-_\s]*(part|chunk|seg|p)\s*\d{1,4}$|[\-_\s]*\d{1,4}$)",
    re.IGNORECASE,
)


def _normalize_stem(stem):
    s = stem
    for _ in range(3):
        s2 = _SHARD_TAIL.sub("", s).strip("-_ ")
        if s2 == s:
            break
        s = s2
    return s.lower()


def detect_shard_groups(db):
    """Group files whose names differ only by part/sequence suffixes."""
    ensure_frag_tables(db)
    rows = db.execute("SELECT path, hash FROM locations").fetchall()
    groups = {}
    for path, digest in rows:
        d = os.path.dirname(path)
        stem = os.path.splitext(os.path.basename(path))[0]
        key = (d, _normalize_stem(stem))
        groups.setdefault(key, []).append((path, digest))
    found = []
    db.execute("DELETE FROM frag_clusters WHERE method='name-shards'")
    for (d, norm), members in groups.items():
        if len(members) >= 2 and norm:
            found.append({"dir": d, "stem": norm, "members": members})
            cid = uuid.uuid4().hex[:10]
            db.executemany(
                "INSERT INTO frag_clusters VALUES (?,?,?,?)",
                [(cid, "name-shards", h, p) for p, h in members],
            )
    db.commit()
    return found
