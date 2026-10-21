import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from guicang.autopilot import (
    classify_all,
    dedup_plan,
    execute_quarantine,
    expire_plan,
    protect_plan,
    restore_quarantine,
)
from guicang.core import Registry
from guicang.nodes import add_node, scan_node


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def run():
    tmp = tempfile.mkdtemp()
    root = os.path.join(tmp, "files")
    final_video = os.path.join(root, "deliverables", "片名-终版.mp4")
    copy_video = os.path.join(root, "downloads", "片名-终版 (2).mp4")
    temp_doc = os.path.join(root, "docs", "~$报告.docx")
    normal_doc = os.path.join(root, "docs", "季度报告.md")
    write(final_video, b"VIDEO" * 500)
    write(copy_video, b"VIDEO" * 500)
    write(temp_doc, b"TEMP")
    write(normal_doc, "正文内容".encode())

    db = os.path.join(tmp, "t.db")
    reg = Registry(db)
    add_node(reg, "n", root, "local")
    scan_node(reg, "n")

    out = classify_all(db)
    assert out["importance"]["protect"] >= 1, out
    assert out["importance"]["ephemeral"] >= 1, out

    # dedup: the stray copy is planned, the final in deliverables is not
    d = dedup_plan(db)
    paths = [a["path"] for a in d["actions"]]
    assert copy_video in paths and final_video not in paths, d
    assert d["reclaimable"] == 2500

    # expire: temp file listed; normal + final never listed anywhere
    e = expire_plan(db)
    epaths = [a["path"] for a in e["actions"]]
    assert temp_doc in epaths
    assert normal_doc not in epaths and final_video not in epaths

    # protection: final video counts as protect, flagged single-copy
    p = protect_plan(db)
    assert p["protect_total"] >= 1 and len(p["at_risk"]) >= 1

    # quarantine is a move with a log; restore brings everything back
    q = execute_quarantine(db, d["actions"] + e["actions"], os.path.join(tmp, "q"))
    assert len(q["moved"]) == 2 and not os.path.exists(copy_video)
    assert os.path.exists(final_video) and os.path.exists(normal_doc)
    r = restore_quarantine(db)
    assert len(r["restored"]) == 2 and os.path.exists(copy_video)

    print("AUTOPILOT TESTS PASSED")


if __name__ == "__main__":
    run()
