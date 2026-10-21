import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mm1031.core import Registry, load_manifest_for


def write(path, data):
    with open(path, "wb") as f:
        f.write(data)


def run():
    tmp = tempfile.mkdtemp()
    reg = Registry(os.path.join(tmp, "t.db"))
    proj = os.path.join(tmp, "proj")
    os.makedirs(proj)

    # v1: a script produced by an LLM, with sidecar manifest
    f1 = os.path.join(proj, "script.md")
    write(f1, "第一版旁白稿".encode())
    manifest = {
        "asset_key": "tahoe::script",
        "name": "太浩湖旁白稿",
        "project": "太浩湖航拍片",
        "intent": "正片旁白",
        "provenance": {
            "tool": "Claude",
            "model": "claude-sonnet",
            "prompt": "写一段太浩湖旁白",
            "inputs": [],
            "params": {},
        },
    }
    with open(f1 + ".mm1031.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False)
    aid, seq, is_new = reg.register(f1, load_manifest_for(f1))
    assert is_new and seq == 1, (aid, seq, is_new)

    # v2: same asset_key, changed content -> version 2
    write(f1, "第二版旁白稿，改了开头".encode())
    aid2, seq2, is_new2 = reg.register(f1, load_manifest_for(f1))
    assert aid2 == aid and seq2 == 2 and not is_new2
    assert len(reg.versions_of(aid)) == 2

    # provenance is recorded
    v = reg.versions_of(aid)[0]
    assert v["tool"] == "Claude" and v["model"] == "claude-sonnet"

    # dedup: same bytes at a second path -> one blob, wasted counted
    f2 = os.path.join(tmp, "copy-of-v2.md")
    write(f2, "第二版旁白稿，改了开头".encode())
    reg.register(f2, {"asset_key": "other::copy", "project": "杂项"})
    report = reg.dedup_report()
    assert report and report[0]["copies"] == 2 and report[0]["wasted"] > 0

    # inbox + promote + search
    assert any(r["id"] == aid for r in reg.inbox())
    reg.promote(aid, "final")
    assert not any(r["id"] == aid for r in reg.inbox())
    hits = reg.search("太浩湖")
    assert hits and hits[0]["state"] == "final"

    print("ALL TESTS PASSED")


if __name__ == "__main__":
    run()
