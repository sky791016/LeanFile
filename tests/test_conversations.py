import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from guicang.core import Registry
from guicang.preview import conversation_tree, infer_conversation_batches
from guicang.nodes import add_node, scan_node


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def run():
    tmp = tempfile.mkdtemp()
    db = os.path.join(tmp, "t.db")
    reg = Registry(db)

    # 1) explicit conversation at register time
    f1 = os.path.join(tmp, "太浩湖解说词.md")
    write(f1, "解说词正文".encode())
    reg.register(
        f1,
        {
            "asset_key": "tahoe-script",
            "name": "太浩湖解说词",
            "type": "document",
            "provenance": {
                "tool": "Claude",
                "model": "claude-x",
                "conversation": {
                    "id": "sess-tahoe",
                    "title": "太浩湖视频制作",
                    "tool": "Claude",
                    "model": "claude-x",
                },
            },
        }
    )
    tree = conversation_tree(db)
    assert len(tree) == 1 and tree[0]["title"] == "太浩湖视频制作"
    assert tree[0]["files"] == 1 and not tree[0]["inferred"]

    # 2) inferred sessions split by time gap: 2 files close, 1 ten hours later
    root = os.path.join(tmp, "legacy")
    a = os.path.join(root, "a.md"); write(a, b"A")
    b = os.path.join(root, "b.md"); write(b, b"B")
    c = os.path.join(root, "c.md"); write(c, b"C")
    base = time.time() - 86400 * 3
    os.utime(a, (base, base))
    os.utime(b, (base + 600, base + 600))
    os.utime(c, (base + 36000, base + 36000))
    reg2 = Registry(db)
    add_node(reg2, "n", root, "local")
    scan_node(reg2, "n")
    out = infer_conversation_batches(db)
    assert out["batches"] == 1, out  # only the 2-file window forms a batch
    assert out["versions_linked"] == 2
    tree = conversation_tree(db)
    inferred = [t for t in tree if t["inferred"]]
    assert len(inferred) == 1 and inferred[0]["files"] == 2

    print("CONVERSATION TESTS PASSED")


if __name__ == "__main__":
    run()
