import hashlib
import json
import os
import sqlite3
import time
import uuid

HASH_ALGO = "blake2b-256"  # prototype stand-in; production target BLAKE3
STATES = ("draft", "candidate", "final", "published", "archived")


def hash_file(path, chunk=1 << 20):
    h = hashlib.blake2b(digest_size=32)
    with open(path, "rb") as f:
        while True:
            data = f.read(chunk)
            if not data:
                break
            h.update(data)
    return h.hexdigest()


def guess_type(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".md", ".txt", ".docx", ".pdf"):
        return "document"
    if ext in (".png", ".jpg", ".jpeg", ".webp", ".heic"):
        return "image"
    if ext in (".mp4", ".mov", ".mkv"):
        return "video"
    if ext in (".mp3", ".wav", ".m4a"):
        return "audio"
    if ext in (".pptx", ".key"):
        return "slides"
    return "file"


class Registry:
    def __init__(self, db_path):
        self.db = sqlite3.connect(db_path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS blobs(
              hash TEXT PRIMARY KEY, size INTEGER, algo TEXT);
            CREATE TABLE IF NOT EXISTS blob_locations(
              hash TEXT, path TEXT, PRIMARY KEY(hash, path));
            CREATE TABLE IF NOT EXISTS assets(
              id TEXT PRIMARY KEY, akey TEXT UNIQUE, name TEXT,
              project TEXT, atype TEXT, state TEXT, in_inbox INTEGER,
              created REAL);
            CREATE TABLE IF NOT EXISTS versions(
              id TEXT PRIMARY KEY, asset_id TEXT, seq INTEGER,
              blob_hash TEXT, note TEXT, author TEXT, created REAL);
            CREATE TABLE IF NOT EXISTS enrichments(
              id INTEGER PRIMARY KEY AUTOINCREMENT, asset_id TEXT,
              feature TEXT, provider TEXT, model TEXT,
              cost_units INTEGER, created REAL);
            CREATE TABLE IF NOT EXISTS provenance(
              version_id TEXT PRIMARY KEY, tool TEXT, model TEXT,
              prompt TEXT, prompt_hash TEXT, inputs TEXT,
              params TEXT, intent TEXT);
            CREATE TABLE IF NOT EXISTS conversations(
              id TEXT PRIMARY KEY, tool TEXT, model TEXT, title TEXT,
              inferred INTEGER, created REAL);
            """
        )
        for idx_sql in (
            "CREATE INDEX IF NOT EXISTS idx_versions_asset "
            "ON versions(asset_id, seq)",
            "CREATE INDEX IF NOT EXISTS idx_versions_blob "
            "ON versions(blob_hash)",
            "CREATE INDEX IF NOT EXISTS idx_locations_hash "
            "ON locations(hash)",
            "CREATE INDEX IF NOT EXISTS idx_provenance_conv "
            "ON provenance(conversation_id)",
            "CREATE INDEX IF NOT EXISTS idx_assets_state "
            "ON assets(state)",
            "CREATE INDEX IF NOT EXISTS idx_assets_category "
            "ON assets(category)",
        ):
            try:
                self.db.execute(idx_sql)
            except Exception:
                pass  # table may not exist yet (locations comes from nodes)
        cols = [r[1] for r in self.db.execute("PRAGMA table_info(provenance)")]
        if "conversation_id" not in cols:
            self.db.execute(
                "ALTER TABLE provenance ADD COLUMN conversation_id TEXT"
            )
        self.db.commit()

    def register(self, path, manifest=None, author="human"):
        """Register a file. Returns (asset_id, version_seq, is_new_asset).

        Identity = content hash. Sameness of *asset* (for versioning)
        comes from the manifest asset_key, else project+stem.
        """
        manifest = manifest or {}
        abspath = os.path.abspath(path)
        digest = hash_file(abspath)
        size = os.path.getsize(abspath)
        self.db.execute(
            "INSERT OR IGNORE INTO blobs VALUES (?,?,?)",
            (digest, size, HASH_ALGO),
        )
        self.db.execute(
            "INSERT OR IGNORE INTO blob_locations VALUES (?,?)",
            (digest, abspath),
        )
        stem = os.path.splitext(os.path.basename(abspath))[0]
        project = manifest.get("project") or "未归类"
        akey = manifest.get("asset_key") or (project + "::" + stem)
        row = self.db.execute(
            "SELECT * FROM assets WHERE akey=?", (akey,)
        ).fetchone()
        now = time.time()
        if row is None:
            asset_id = uuid.uuid4().hex[:12]
            self.db.execute(
                "INSERT INTO assets VALUES (?,?,?,?,?,?,1,?)",
                (
                    asset_id,
                    akey,
                    manifest.get("name") or stem,
                    project,
                    manifest.get("type") or guess_type(abspath),
                    "draft",
                    now,
                ),
            )
            seq = 1
            is_new = True
        else:
            asset_id = row["id"]
            seq = self.db.execute(
                "SELECT COALESCE(MAX(seq),0)+1 AS s FROM versions WHERE asset_id=?",
                (asset_id,),
            ).fetchone()["s"]
            self.db.execute(
                "UPDATE assets SET in_inbox=1 WHERE id=?", (asset_id,)
            )
            is_new = False
        version_id = uuid.uuid4().hex[:12]
        self.db.execute(
            "INSERT INTO versions VALUES (?,?,?,?,?,?,?)",
            (
                version_id,
                asset_id,
                seq,
                digest,
                manifest.get("note") or "",
                manifest.get("author") or author,
                now,
            ),
        )
        prov = manifest.get("provenance") or {}
        prompt = prov.get("prompt") or ""
        conv = prov.get("conversation") or manifest.get("conversation") or {}
        conversation_id = ""
        if conv:
            conversation_id = conv.get("id") or uuid.uuid4().hex[:12]
            self.db.execute(
                "INSERT OR IGNORE INTO conversations VALUES (?,?,?,?,0,?)",
                (
                    conversation_id,
                    conv.get("tool") or prov.get("tool") or "",
                    conv.get("model") or prov.get("model") or "",
                    conv.get("title") or "",
                    now,
                ),
            )
        self.db.execute(
            "INSERT INTO provenance(version_id, tool, model, prompt, "
            "prompt_hash, inputs, params, intent, conversation_id) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                version_id,
                prov.get("tool") or "",
                prov.get("model") or "",
                prompt,
                hashlib.sha256(prompt.encode()).hexdigest() if prompt else "",
                json.dumps(prov.get("inputs") or [], ensure_ascii=False),
                json.dumps(prov.get("params") or {}, ensure_ascii=False),
                manifest.get("intent") or "",
                conversation_id,
            ),
        )
        self.db.commit()
        return asset_id, seq, is_new

    def log_enrichment(self, asset_id, feature, provider, model, cost_units):
        """Compute provenance: who computed what, with which model, at what cost."""
        self.db.execute(
            "INSERT INTO enrichments(asset_id, feature, provider, model, "
            "cost_units, created) VALUES (?,?,?,?,?,?)",
            (asset_id, feature, provider, model, cost_units, time.time()),
        )
        self.db.commit()

    def promote(self, asset_id, to_state="final"):
        if to_state not in STATES:
            raise ValueError("bad state: " + to_state)
        self.db.execute(
            "UPDATE assets SET state=?, in_inbox=0 WHERE id=?",
            (to_state, asset_id),
        )
        self.db.commit()

    def inbox(self):
        return self.db.execute(
            "SELECT a.*, (SELECT MAX(seq) FROM versions v WHERE v.asset_id=a.id) "
            "AS latest_seq FROM assets a WHERE in_inbox=1 ORDER BY created"
        ).fetchall()

    def search(self, query):
        like = "%" + query + "%"
        return self.db.execute(
            "SELECT * FROM assets WHERE name LIKE ? OR project LIKE ? ORDER BY created",
            (like, like),
        ).fetchall()

    def versions_of(self, asset_id):
        return self.db.execute(
            "SELECT v.*, p.tool, p.model, p.intent FROM versions v "
            "LEFT JOIN provenance p ON p.version_id=v.id "
            "WHERE v.asset_id=? ORDER BY v.seq",
            (asset_id,),
        ).fetchall()

    def dedup_report(self):
        rows = self.db.execute(
            "SELECT b.hash, b.size, COUNT(l.path) AS n FROM blobs b "
            "JOIN blob_locations l ON l.hash=b.hash "
            "GROUP BY b.hash HAVING n>1 ORDER BY b.size DESC"
        ).fetchall()
        return [
            {
                "hash": r["hash"][:12],
                "copies": r["n"],
                "size_each": r["size"],
                "wasted": r["size"] * (r["n"] - 1),
            }
            for r in rows
        ]


def load_manifest_for(path):
    """Sidecar convention: <file>.guicang.json next to the asset."""
    sidecar = path + ".guicang.json"
    if os.path.exists(sidecar):
        with open(sidecar, encoding="utf-8") as f:
            return json.load(f)
    return None
