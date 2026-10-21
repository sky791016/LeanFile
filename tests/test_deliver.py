import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mm1031.core import Registry
from mm1031.nodes import add_node, scan_node
from mm1031.autopilot import classify_all, protect_plan
from mm1031.deliver import export_bundle, protect_run


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def run():
    tmp = tempfile.mkdtemp()
    db = os.path.join(tmp, "t.db")
    reg = Registry(db)

    # ---- bundle: one conversation, two files with the same basename
    conv = {"id": "sess-1", "title": "季度报告制作", "tool": "Claude",
            "model": "claude-x"}
    for sub, body in (("a", "报告正文A"), ("b", "报告正文B-更长")):
        f = os.path.join(tmp, sub, "report.md")
        write(f, body.encode())
        reg.register(f, {
            "asset_key": f"rpt-{sub}", "name": f"报告{sub}", "type": "document",
            "provenance": {"tool": "Claude", "model": "claude-x",
                           "conversation": conv},
        })
    other = os.path.join(tmp, "c", "other.md")
    write(other, "无关文件".encode())
    reg.register(other, {"asset_key": "other", "name": "无关",
                         "type": "document"})

    out = export_bundle(db, latest=True,
                        out_root=os.path.join(tmp, "exports"))
    assert out["count"] == 2, out
    names = sorted(os.listdir(out["dir"]))
    assert "report.md" in names and "report (2).md" in names, names
    assert "BUNDLE.md" in names and "bundle.json" in names
    man = json.load(open(os.path.join(out["dir"], "bundle.json")))
    assert man["conversation"]["id"] == "sess-1" and len(man["files"]) == 2
    out2 = export_bundle(db, "sess", out_root=os.path.join(tmp, "e2"))
    assert out2["count"] == 2
    assert export_bundle(db, "nope").get("error") == "conversation_not_found"
    print("bundle OK")

    # ---- protect-run: final asset living on one node only
    dir_a = os.path.join(tmp, "mainstore")
    dir_b = os.path.join(tmp, "backupstore")
    os.makedirs(dir_a)
    os.makedirs(dir_b)
    write(os.path.join(dir_a, "合同终版.pdf"), b"%PDF-final-contract")
    reg2 = Registry(db)
    add_node(reg2, "main", dir_a)
    add_node(reg2, "backup", dir_b)
    scan_node(reg2, "main")
    reg2.db.execute("UPDATE assets SET state='final' WHERE name LIKE '%合同%'")
    reg2.db.commit()
    classify_all(db)
    plan = protect_plan(db)
    assert any("合同" in n for n in plan["at_risk"]), plan
    planned = protect_run(db, target_node="backup")
    assert len(planned["planned"]) >= 1 and not planned["done"]
    done = protect_run(db, target_node="backup", execute=True)
    assert len(done["done"]) >= 1
    dest = done["done"][0]["dest"]
    assert dest.startswith(dir_b) and os.path.exists(dest)
    plan2 = protect_plan(db)
    assert not any("合同" in n for n in plan2["at_risk"]), plan2
    print("protect-run OK")


if __name__ == "__main__":
    run()
    print("ALL DELIVER TESTS PASSED")
