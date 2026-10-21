import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mm1031.core import Registry
from mm1031.nodes import add_node, scan_node
from mm1031.organize import execute_plan, filing_plan, undo


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def locs(db_path):
    db = sqlite3.connect(db_path)
    out = [r[0] for r in db.execute("SELECT path FROM locations")]
    db.close()
    return out


def run():
    tmp = tempfile.mkdtemp()
    drop = os.path.join(tmp, "drop")
    lib = os.path.join(tmp, "library")
    os.makedirs(drop)
    reg = Registry(os.path.join(tmp, "t.db"))
    add_node(reg, "drop", drop, "local")
    db_path = os.path.join(tmp, "t.db")

    src = os.path.join(drop, "messy-name.csv")
    write(src, b"a,b\n1,2\n")
    write(os.path.join(drop, "notes.md"), "# hi\n".encode())
    scan_node(reg, "drop")

    plan = filing_plan(db_path, "drop", lib)
    assert len(plan) == 2, plan
    csv_move = [p for p in plan if p["name"] == "messy-name.csv"][0]
    assert "表格数据" in csv_move["to"], csv_move
    assert csv_move["to"].startswith(lib), csv_move

    manifest = os.path.join(tmp, "manifest.json")
    n = execute_plan(db_path, plan, manifest)
    assert n == 2
    assert os.path.exists(csv_move["to"])
    assert not os.path.exists(src)
    assert csv_move["to"] in locs(db_path), locs(db_path)
    # re-planning after execution: nothing left to file
    assert filing_plan(db_path, "drop", lib) == []

    back = undo(db_path, manifest)
    assert back == 2
    assert os.path.exists(src)
    assert src in locs(db_path), locs(db_path)

    print("ORGANIZE TESTS PASSED")


if __name__ == "__main__":
    run()
