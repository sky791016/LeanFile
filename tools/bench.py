"""Stress bench: ingest rate + de-fragmentation quality vs ground truth."""
import json
import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from guicang.engine import cluster_text_variants, detect_shard_groups, parallel_ingest


def main(root, truth_path, db_path):
    if os.path.exists(db_path):
        os.remove(db_path)
    t0 = time.time()
    stats = parallel_ingest(db_path, root, "bench")
    ingest_s = time.time() - t0
    total_files = stats["ingested"] + stats["skipped_unchanged"]
    print(f"INGEST {stats} total={ingest_s:.1f}s "
          f"rate={stats['ingested']/max(ingest_s,0.01):.0f} files/s")

    # incremental re-run should be near-instant (all skipped)
    t0 = time.time()
    stats2 = parallel_ingest(db_path, root, "bench")
    print(f"REINGEST {stats2} total={time.time()-t0:.1f}s")

    db = sqlite3.connect(db_path)
    truth = json.load(open(truth_path))
    root_abs = os.path.abspath(root)

    # exact-copy recovery
    dup_groups = db.execute(
        "SELECT COUNT(*) FROM (SELECT hash FROM blob_locations "
        "GROUP BY hash HAVING COUNT(*)>1)"
    ).fetchone()[0]
    print(f"EXACT-DUP groups in registry: {dup_groups} "
          f"(planted copy pairs: {len(truth['copy_pairs'])})")

    # simhash variant clustering: pair recall + pair precision
    t0 = time.time()
    out = cluster_text_variants(db)
    cluster_of = {}
    for idx, g in enumerate(out["clusters"]):
        for h in g:
            cluster_of[h] = idx
    hash_of_path = {}
    for rel_hash, path in db.execute("SELECT hash, path FROM locations"):
        hash_of_path[os.path.relpath(path, root_abs)] = rel_hash
    planted_pairs, hit_pairs = 0, 0
    for group in truth["variant_groups"]:
        hs = [hash_of_path[g] for g in group if g in hash_of_path]
        for i in range(len(hs)):
            for j in range(i + 1, len(hs)):
                planted_pairs += 1
                if cluster_of.get(hs[i]) is not None and cluster_of.get(hs[i]) == cluster_of.get(hs[j]):
                    hit_pairs += 1
    # precision: pairs inside clusters that are truly same-family
    family = {}
    for gi, group in enumerate(truth["variant_groups"]):
        for g in group:
            if g in hash_of_path:
                family[hash_of_path[g]] = gi
    in_pairs, good_pairs = 0, 0
    for g in out["clusters"]:
        for i in range(len(g)):
            for j in range(i + 1, len(g)):
                in_pairs += 1
                if family.get(g[i]) is not None and family.get(g[i]) == family.get(g[j]):
                    good_pairs += 1
    print(f"SIMHASH fingerprinted={out['fingerprinted']} clusters={len(out['clusters'])} "
          f"({time.time()-t0:.1f}s)")
    print(f"  variant pair recall: {hit_pairs}/{planted_pairs} = {hit_pairs/max(planted_pairs,1):.1%}")
    print(f"  cluster pair precision: {good_pairs}/{in_pairs} = {good_pairs/max(in_pairs,1):.1%}")

    # shard groups by naming pattern
    found = detect_shard_groups(db)
    found_sets = [set(p for p, _ in g["members"]) for g in found]
    recovered = 0
    for planted in truth["shard_groups"]:
        planted_abs = {os.path.join(root_abs, r) for r in planted}
        if any(len(planted_abs & s) >= 2 and planted_abs >= (planted_abs & s) for s in found_sets):
            if any(planted_abs & s == planted_abs or len(planted_abs & s) >= 2 for s in found_sets):
                recovered += 1
    print(f"SHARDS planted={len(truth['shard_groups'])} "
          f"pattern-groups found={len(found)} recovered={recovered}")

    # full-text index build + query latency (FSearch-style instant search)
    from guicang.engine import build_content_index, search_content

    t0 = time.time()
    info = build_content_index(db)
    build_s = time.time() - t0
    print(f"FTS indexed={info['indexed']} in {build_s:.1f}s")
    for q in ("w0001", "w0420 w0777", "标题"):
        t0 = time.time()
        hits = search_content(db, q)
        ms = (time.time() - t0) * 1000
        print(f"  query {q!r}: {len(hits)} hits in {ms:.1f} ms")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
