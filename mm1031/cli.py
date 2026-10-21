import argparse
import json
import os
import sys

from .core import Registry, load_manifest_for


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mm1031")
    ap.add_argument("--db", default="mm1031.db")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("register")
    p.add_argument("file")
    p.add_argument("--manifest", help="path to a .mm1031.json manifest")

    sub.add_parser("inbox")

    p = sub.add_parser("promote")
    p.add_argument("asset_id")
    p.add_argument("--to", default="final")

    p = sub.add_parser("search")
    p.add_argument("query")

    p = sub.add_parser("versions")
    p.add_argument("asset_id")

    sub.add_parser("dedup")

    p = sub.add_parser("node-add")
    p.add_argument("name")
    p.add_argument("path")
    p.add_argument("--kind", default="local")

    sub.add_parser("node-list")

    p = sub.add_parser("scan")
    p.add_argument("node")

    sub.add_parser("coverage")

    p = sub.add_parser("replicate")
    p.add_argument("target_node")
    p.add_argument("--execute", action="store_true")

    sub.add_parser("autopilot-classify")

    p = sub.add_parser("autopilot-plan")
    p.add_argument("--full", action="store_true", help="print every action")

    p = sub.add_parser("autopilot-run")
    p.add_argument("--quarantine-dir", default="mm1031-quarantine")
    p.add_argument("--yes", action="store_true",
                   help="required: confirms the plan shown by autopilot-plan")

    sub.add_parser("autopilot-restore")

    p = sub.add_parser("rules")
    p.add_argument("kv", nargs="?", help="key=value to set; empty lists rules")

    p = sub.add_parser("cleanup-plan")

    p = sub.add_parser("cleanup-run")
    p.add_argument("--quarantine-dir", default="mm1031-quarantine")

    p = sub.add_parser("build-previews")
    p.add_argument("--cache", default="preview-cache")
    p.add_argument("--no-ql", action="store_true")

    sub.add_parser("infer-batches")

    p = sub.add_parser("bundle")
    p.add_argument("conversation", nargs="?", help="id prefix or title keyword")
    p.add_argument("--latest", action="store_true", help="bundle the most recent conversation")
    p.add_argument("--out", help="output directory (default ~/LeanFile-Exports/...)")

    p = sub.add_parser("protect-run")
    p.add_argument("--to", dest="target", help="target node name")
    p.add_argument("--yes", action="store_true", help="execute the copies (default: plan only)")

    sub.add_parser("shards")

    p = sub.add_parser("conversations")
    p.add_argument("--files", action="store_true", help="list files per conversation")

    p = sub.add_parser("summarize")
    p.add_argument("file")
    p.add_argument("--config", default="mm1031.config.json")
    p.add_argument("--asset", help="asset id to log compute provenance against")

    p = sub.add_parser("tag-all")
    p.add_argument("--content", action="store_true",
                   help="also generate content keyword tags from excerpts")
    p.add_argument("--config", default="mm1031.config.json")
    p.add_argument("--refresh-content", action="store_true")

    sub.add_parser("facets")

    p = sub.add_parser("tag-filter")
    p.add_argument("--tag", action="append", default=[],
                   help="dim:value, repeatable; AND across dims")

    p = sub.add_parser("organize-plan")
    p.add_argument("node")
    p.add_argument("--to", required=True, help="library root directory")

    p = sub.add_parser("organize-run")
    p.add_argument("node")
    p.add_argument("--to", required=True, help="library root directory")
    p.add_argument("--manifest", default="organize-manifest.json")
    p.add_argument("--yes", action="store_true",
                   help="required: confirms the organize-plan output")

    p = sub.add_parser("organize-undo")
    p.add_argument("--manifest", default="organize-manifest.json")

    args = ap.parse_args(argv)
    reg = Registry(args.db)

    if args.cmd == "register":
        manifest = None
        if args.manifest:
            with open(args.manifest, encoding="utf-8") as f:
                manifest = json.load(f)
        else:
            manifest = load_manifest_for(args.file)
        asset_id, seq, is_new = reg.register(args.file, manifest)
        print(
            json.dumps(
                {
                    "asset_id": asset_id,
                    "version": seq,
                    "new_asset": is_new,
                    "state": "draft",
                    "inbox": True,
                },
                ensure_ascii=False,
            )
        )
    elif args.cmd == "inbox":
        for r in reg.inbox():
            print(
                f"[{r['id']}] {r['name']} · {r['project']} · "
                f"v{r['latest_seq']} · 状态={r['state']}"
            )
    elif args.cmd == "promote":
        reg.promote(args.asset_id, args.to)
        print(f"已设为正式版 (Set as Final): {args.asset_id} -> {args.to}")
    elif args.cmd == "search":
        for r in reg.search(args.query):
            print(f"[{r['id']}] {r['name']} · {r['project']} · 状态={r['state']}")
    elif args.cmd == "versions":
        for v in reg.versions_of(args.asset_id):
            print(
                f"v{v['seq']} · {v['blob_hash'][:12]} · {v['author']} · "
                f"工具={v['tool'] or '-'} 模型={v['model'] or '-'} · {v['note']}"
            )
    elif args.cmd == "dedup":
        rows = reg.dedup_report()
        total = sum(r["wasted"] for r in rows)
        for r in rows:
            print(
                f"哈希 {r['hash']} · {r['copies']} 份副本 · "
                f"每份 {r['size_each']} B · 可回收 {r['wasted']} B"
            )
        print(f"合计可回收: {total} B（物理只存一份，此为逻辑重复量）")
    elif args.cmd == "node-add":
        from .nodes import add_node

        add_node(reg, args.name, args.path, args.kind)
        print(f"节点已登记: {args.name} -> {args.path} ({args.kind})")
    elif args.cmd == "node-list":
        from .nodes import list_nodes

        for n in list_nodes(reg):
            print(f"{n['name']} · {n['kind']} · {n['path']}")
    elif args.cmd == "scan":
        from .nodes import scan_node

        print(scan_node(reg, args.node))
    elif args.cmd == "coverage":
        from .nodes import coverage

        cov = coverage(reg)
        for e in cov["protected"]:
            print(f"已保护 · {e['asset']} · 节点 {e['nodes']}")
        for e in cov["at_risk"]:
            print(f"有风险 · {e['asset']} · 仅在 {e['nodes']}")
    elif args.cmd == "replicate":
        from .nodes import replicate

        out = replicate(reg, args.target_node, execute=args.execute)
        for item in out["planned"]:
            verb = "已复制" if args.execute else "计划复制"
            print(f"{verb} · {item['asset']} -> {item['dest']}")
        if not out["planned"]:
            print("无待复制项：定稿资产在目标节点均有副本")
    elif args.cmd == "autopilot-classify":
        from .autopilot import classify_all

        print(classify_all(args.db))
    elif args.cmd == "autopilot-plan":
        from .autopilot import dedup_plan, expire_plan, protect_plan

        d = dedup_plan(args.db)
        e = expire_plan(args.db)
        p = protect_plan(args.db)
        print(f"自动去重：{len(d['actions'])} 个多余副本，可回收 {d['reclaimable']} B")
        print(f"过期清理：{len(e['actions'])} 个临时/中间文件，可回收 {e['reclaimable']} B")
        print(f"重要文件：共 {p['protect_total']} 个，其中 {len(p['at_risk'])} 个只有一份副本（有丢失风险）")
        show = (d["actions"] + e["actions"]) if args.full else (d["actions"] + e["actions"])[:15]
        for a in show:
            print(f"  [{a['reason']}] {a['path']} ({a['size']} B)")
    elif args.cmd == "autopilot-run":
        if not args.yes:
            print("安全纪律：先跑 autopilot-plan 看清单，确认后加 --yes 执行（移入隔离区，可恢复）")
            return 1
        from .autopilot import dedup_plan, execute_quarantine, expire_plan

        actions = dedup_plan(args.db)["actions"] + expire_plan(args.db)["actions"]
        out = execute_quarantine(args.db, actions, args.quarantine_dir)
        print(f"已移入隔离区：{len(out['moved'])} 个；失败：{len(out['failed'])} 个（全部有日志，可 autopilot-restore 恢复）")
    elif args.cmd == "rules":
        from .autopilot import get_rules, set_rule

        if args.kv and "=" in args.kv:
            k, v = args.kv.split("=", 1)
            set_rule(args.db, k, v)
            print(f"规则已设置 rule set: {k}={v}")
        else:
            for k, v in get_rules(args.db).items():
                print(f"  {k} = {v}")
    elif args.cmd == "cleanup-plan":
        from .autopilot import cleanup_plan

        parts = cleanup_plan(args.db)
        for name, p in parts.items():
            print(f"{name}: {len(p['actions'])} 个文件, 可回收 {p['reclaimable']} B")
            for a in p["actions"][:10]:
                print(f"  [{a['reason']}] {a['path']}")
    elif args.cmd == "cleanup-run":
        from .autopilot import run_cleanup

        out = run_cleanup(args.db, args.quarantine_dir)
        print(f"计划 planned: {out['planned']}")
        print(f"已移入隔离区 moved: {len(out['moved'])}；失败 failed: {len(out['failed'])}；过期销毁 purged: {len(out['purged'])}")
    elif args.cmd == "autopilot-restore":
        from .autopilot import restore_quarantine

        print(restore_quarantine(args.db))
    elif args.cmd == "build-previews":
        from .preview import build_previews

        print(build_previews(args.db, args.cache, use_ql=not args.no_ql))
    elif args.cmd == "conversations":
        from .preview import conversation_tree

        for c in conversation_tree(args.db):
            tag = "推断 inferred" if c["inferred"] else "实录 recorded"
            print(f"[{tag}] {c['title']} | 工具 {c['tool'] or '-'} | 文件 {c['files']} 个 | {c['bytes']} B")
            if args.files:
                for it in c["items"]:
                    print(f"    · {it['name']} ({it['atype']}, {it['state']})")
    elif args.cmd == "bundle":
        from .deliver import export_bundle

        out = export_bundle(args.db, args.conversation,
                            latest=args.latest, out_root=args.out)
        if out.get("error"):
            print("打包失败:", out["error"])
        else:
            print(f"已打包 · {out['title']} · {out['count']} 个文件 · {out['bytes']} B")
            print("目录:", out["dir"])
            for m in out["missing"]:
                print("缺失（源文件不在磁盘）:", m)
    elif args.cmd == "protect-run":
        from .deliver import protect_run

        out = protect_run(args.db, target_node=args.target, execute=args.yes)
        if out.get("error"):
            print("补副本失败:", out["error"])
        else:
            verb = "已复制" if args.yes else "计划复制"
            items = out["done"] if args.yes else out["planned"]
            print(f"重要文件共 {out['protect_total']} 个 · 目标位置 {out['target']} · {verb} {len(items)} 个")
            for it in items:
                print(f"  · {it['asset']} -> {it['dest']}")
            for sk in out["skipped"]:
                print(f"  跳过 · {sk['asset']}（{sk['why']}）")
    elif args.cmd == "shards":
        from .engine import detect_shard_groups
        from . import nodes as nodes_mod

        reg = Registry(args.db)
        nodes_mod.ensure_tables(reg)
        groups = detect_shard_groups(reg.db)
        print(f"分片组 {len(groups)} 组（同名分片、本可拼回一个整体）")
        for g in groups:
            print(f"  · {g['stem']} · {len(g['members'])} 片 · {g['dir']}")
            for pth, _h in g["members"]:
                print(f"      - {os.path.basename(pth)}")
    elif args.cmd == "infer-batches":
        from .preview import infer_conversation_batches

        print(infer_conversation_batches(args.db))
    elif args.cmd == "summarize":
        from .compute import build_chain, load_config

        with open(args.file, encoding="utf-8", errors="replace") as f:
            text = f.read()
        chain = build_chain(load_config(args.config))
        result = chain.summarize(text)
        print(result.text)
        print("算力来历: " + json.dumps(result.provenance(), ensure_ascii=False))
        if args.asset:
            reg.log_enrichment(
                args.asset,
                "summarize",
                result.provider,
                result.model,
                result.cost_units,
            )
    elif args.cmd == "tag-all":
        from .tagging import tag_all

        print(tag_all(args.db, content=args.content,
                      config_path=args.config,
                      refresh_content=args.refresh_content))
    elif args.cmd == "facets":
        from .tagging import facets

        for dim, items in facets(args.db).items():
            print(f"[{dim}] " + " · ".join(
                f"{t}×{n}" for t, n in items[:12]))
    elif args.cmd == "tag-filter":
        from .tagging import filter_assets

        wanted = {}
        for item in args.tag:
            dim, _, value = item.partition(":")
            wanted.setdefault(dim, []).append(value)
        ids = filter_assets(args.db, wanted)
        names = {
            r[0]: r[1]
            for r in reg.db.execute("SELECT id, name FROM assets")
        }
        for aid in ids:
            print(f"{names.get(aid, '?')}  [{aid[:8]}]")
        print(f"共 {len(ids)} 个")
    elif args.cmd == "organize-plan":
        from .organize import filing_plan

        plan = filing_plan(args.db, args.node, args.to)
        for item in plan:
            print(f"{item['from']}  ->  {item['to']}")
        print(f"共 {len(plan)} 个待归档（仅计划，未动任何文件）")
    elif args.cmd == "organize-run":
        from .organize import execute_plan, filing_plan

        if not args.yes:
            print("需要 --yes 确认（先跑 organize-plan 看清单）")
            return 1
        plan = filing_plan(args.db, args.node, args.to)
        n = execute_plan(args.db, plan, args.manifest)
        print(f"已归档 {n} 个文件，清单与撤销记录在 {args.manifest}")
    elif args.cmd == "organize-undo":
        from .organize import undo

        print(f"已撤销 {undo(args.db, args.manifest)} 个文件的归档")
    return 0


if __name__ == "__main__":
    sys.exit(main())
