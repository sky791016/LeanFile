import os
import sqlite3
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from guicang.autopilot import (
    cleanup_plan,
    get_rules,
    restore_quarantine,
    run_cleanup,
    set_rule,
    stale_version_plan,
)
from guicang.core import Registry


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def run():
    tmp = tempfile.mkdtemp()
    db = os.path.join(tmp, "t.db")
    reg = Registry(db)

    # one asset, three SEPARATE files as its versions (v1/v2 = process)
    paths = []
    for i, body in enumerate((b"v1 body", b"v2 body longer", b"v3 final body")):
        f = os.path.join(tmp, f"doc-v{i + 1}.md")
        write(f, body)
        reg.register(f, {"asset_key": "doc", "project": "p"})
        paths.append(f)
    dbc = sqlite3.connect(db)
    dbc.execute("UPDATE versions SET created=? WHERE seq<3", (time.time() - 40 * 86400,))
    dbc.commit()

    plan = stale_version_plan(db, 30)
    got = sorted(a["path"] for a in plan["actions"])
    assert got == sorted(paths[:2]), plan

    # in-place edited asset: old versions share the current path -> safe
    f2 = os.path.join(tmp, "inplace.md")
    write(f2, b"old")
    reg.register(f2, {"asset_key": "inplace", "project": "p"})
    write(f2, b"new content")
    reg.register(f2, {"asset_key": "inplace", "project": "p"})
    dbc = sqlite3.connect(db)
    dbc.execute(
        "UPDATE versions SET created=? WHERE asset_id IN "
        "(SELECT id FROM assets WHERE akey='inplace') AND seq=1",
        (time.time() - 40 * 86400,),
    )
    dbc.commit()
    plan2 = stale_version_plan(db, 30)
    assert all(a["path"] != f2 for a in plan2["actions"]), plan2

    # rules gate everything: switches off -> empty plan; on -> executes
    parts = cleanup_plan(db)
    assert all(len(p["actions"]) == 0 for p in parts.values()), parts
    set_rule(db, "stale_versions_enabled", "1")
    parts = cleanup_plan(db)
    assert len(parts["stale"]["actions"]) == 2
    assert get_rules(db)["stale_versions_days"] == "30"

    out = run_cleanup(db, os.path.join(tmp, "q"))
    assert len(out["moved"]) == 2, out
    assert not os.path.exists(paths[0]) and not os.path.exists(paths[1])
    assert os.path.exists(paths[2]), "current version must survive"
    r = restore_quarantine(db)
    assert len(r["restored"]) == 2

    print("CLEANUP TESTS PASSED")


if __name__ == "__main__":
    run()
