import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mm1031.core import Registry
from mm1031.nodes import add_node, scan_node
from mm1031.preview import build_previews
from mm1031.tagging import facets, filter_assets, tag_all


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def run():
    tmp = tempfile.mkdtemp()
    drop = os.path.join(tmp, "drop")
    os.makedirs(drop)
    reg = Registry(os.path.join(tmp, "t.db"))
    add_node(reg, "drop", drop, "local")

    write(os.path.join(drop, "sales-2026.csv"),
          "month,sales\njan,10\nfeb,20\n".encode())
    write(os.path.join(drop, "数据报告.md"),
          ("# 精益数据方法论实践报告\n"
           "本报告讨论精益数据方法论在制造企业的落地实践，"
           "包括数据治理、数据资产与价值度量。\n").encode("utf-8"))
    write(os.path.join(drop, "clip.mp4"), b"VIDEO" * 50)
    scan_node(reg, "drop")
    db_path = os.path.join(tmp, "t.db")
    build_previews(db_path, os.path.join(tmp, "cache"), use_ql=False)

    stats = tag_all(db_path, content=True)
    assert stats["assets"] == 3, stats
    assert stats["rule_tags"] >= 3 * 4, stats

    f = facets(db_path)
    cats = dict(f["category"])
    assert cats.get("表格数据") == 1, f
    assert cats.get("视频素材") == 1, f
    assert dict(f["ext"]).get(".csv") == 1, f
    months = dict(f["time"])
    assert sum(months.values()) == 3, f

    # combination: category AND extension narrows to exactly the csv
    ids = filter_assets(db_path,
                        {"category": ["表格数据"], "ext": [".csv"]})
    assert len(ids) == 1, ids
    # OR within a dimension: two categories -> two assets
    ids2 = filter_assets(db_path,
                         {"category": ["表格数据", "视频素材"]})
    assert len(ids2) == 2, ids2
    # content tags came from the excerpt of the markdown report
    content = dict(f.get("content", []))
    assert content, f
    ids3 = filter_assets(db_path, {"content": list(content)[:1]})
    assert len(ids3) >= 1, (content, ids3)

    print("TAGGING TESTS PASSED")


if __name__ == "__main__":
    run()
