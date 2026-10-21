import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from guicang.core import Registry
from guicang.nodes import (
    add_node,
    coverage,
    list_nodes,
    replication_plan,
    replicate,
    scan_node,
)


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def run():
    tmp = tempfile.mkdtemp()
    local = os.path.join(tmp, "mac")
    nas = os.path.join(tmp, "nas")
    os.makedirs(local)
    os.makedirs(nas)
    reg = Registry(os.path.join(tmp, "t.db"))

    add_node(reg, "mac-local", local, "local")
    add_node(reg, "synology", nas, "nas")
    assert len(list_nodes(reg)) == 2

    write(os.path.join(local, "film", "final.mp4"), b"FINAL-VIDEO-BYTES" * 100)
    write(os.path.join(local, "film", "draft.mp4"), b"DRAFT" * 10)
    # the same final bytes also sit on the NAS under another name (dup)
    write(os.path.join(nas, "backup", "final-copy.mp4"), b"FINAL-VIDEO-BYTES" * 100)

    # a broken symlink in the tree must be counted, not crash the scan
    os.symlink(os.path.join(local, "no-such-target"), os.path.join(local, "broken-link"))
    s1 = scan_node(reg, "mac-local")
    assert s1["registered"] == 2 and s1["errors"] == 1, s1
    os.remove(os.path.join(local, "broken-link"))
    # incremental scan: unchanged files are skipped, not re-hashed
    s2 = scan_node(reg, "mac-local")
    assert s2["skipped"] == 2 and s2["registered"] == 0, s2

    scan_node(reg, "synology")

    # cross-node dedup now visible from the registry alone
    dups = reg.dedup_report()
    assert any(d["copies"] == 2 for d in dups), dups

    # promote the local final.mp4 to final state
    hits = reg.search("final")
    final_asset = [h for h in hits if h["name"] == "final"][0]
    reg.promote(final_asset["id"], "final")

    cov = coverage(reg)
    # its blob lives on both nodes -> protected
    assert any(e["asset"] == "final" for e in cov["protected"]), cov

    # a second final asset that exists only locally -> at risk + plan
    write(os.path.join(local, "doc", "report.md"), "定稿报告".encode())
    scan_node(reg, "mac-local")
    rep = [h for h in reg.search("report")][0]
    reg.promote(rep["id"], "final")
    cov2 = coverage(reg)
    assert any(e["asset"] == "report" for e in cov2["at_risk"]), cov2

    plan = replication_plan(reg, "synology")
    assert len(plan) == 1 and plan[0]["asset"] == "report", plan
    out = replicate(reg, "synology", execute=False)
    assert out["done"] == []  # plan-only must not copy
    assert not os.path.exists(plan[0]["dest"])
    out = replicate(reg, "synology", execute=True)
    assert len(out["done"]) == 1 and os.path.exists(plan[0]["dest"])
    cov3 = coverage(reg)
    assert any(e["asset"] == "report" for e in cov3["protected"]), cov3

    print("NODE TESTS PASSED")


if __name__ == "__main__":
    run()
