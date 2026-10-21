<p align="center">
  <img src="brand/app-icon-1024.png" width="128" alt="LeanFile 应用图标">
</p>

<h1 align="center">LeanFile</h1>

<p align="center">
  <strong>你的 AI 生成的每一个文件——自动汇聚、自动去重、按对话组织、毫秒级找回。</strong>
</p>

<p align="center">
  <a href="README.md">English</a> ·
  <a href="https://sky791016.github.io/LeanFile/">门户网站</a> ·
  <a href="#快速开始引擎-cli">快速开始</a> ·
  <a href="LICENSE">许可证</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/license-Apache%202.0-blue" alt="许可证：Apache 2.0">
  <img src="https://img.shields.io/badge/platform-macOS%2014%2B-0B2B4B" alt="平台：macOS 14+">
  <img src="https://img.shields.io/badge/core-Python%203-3776AB" alt="核心引擎：Python 3">
  <img src="https://img.shields.io/badge/UI-SwiftUI-orange" alt="界面：SwiftUI">
</p>

AI 工具生产文件的速度，已经超过任何文件夹体系能承受的程度：草稿、
变体、渲染稿、分片——成千上万个近乎相同的文件，散落在多台机器和
NAS 上。LeanFile 是位于你的文件之上的一层“资产层”，安静地把它们
管起来。

> LeanFile 是史凯（Kai Shi）的 Lean 家族一员——与《精益数据方法论》、
> Lean AI、LeanFDE 一脉相承：把精益思想用在大模型时代的文件混乱上。
> （内部代号：`guicang`）

## 它做什么——只要结果，不要过程数据

用户不关心版本图，只关心这七件事：

1. **重复自动消失**——相同内容只留最佳一份，多余副本进隔离区
   （永不硬删），一键可恢复。
2. **文件自动分类**——每个文件都有类别和重要度三档：
   *重要（protect）/ 保留（keep）/ 临时（ephemeral）*。
3. **全文检索真的找得到**——SQLite FTS5 索引文档正文，
   万级文件量下查询 0.5–6 毫秒。
4. **重要文件丢不了**——重要文件被持续监测单副本风险，
   一键复制到第二个存放位置，逐个验哈希才算数。
5. **垃圾按规则过期**——规则由你开关（过程版本保留 N 天、
   隔离区保留期等）；LeanFile 负责执行，永远先隔离、
   永远有日志、永远可恢复。
6. **对话一键打包交付**——把某次对话产出的每个文件的最佳版本，
   打包成一个干净文件夹，附清单（BUNDLE.md），拿来就能发人。
7. **碎片看得见**——本是一体的分片文件（part 文件、序列分片）
   被识别成组列出，碎片拼得回，不再散落。

## 按对话组织

你回想一个文件，想的是“哪次对话产出的”，不是它在哪个文件夹。
LeanFile 按产生文件的那次大模型对话 / 工作会话组织文件：登记时
携带对话元数据（工具、模型、标题）；存量文件按“项目目录 + 时间窗”
重建会话——并如实标注为“推断归组”，绝不冒充事实。

## 总览先行

macOS 应用打开就是总览：文件总数、占用空间、分类与类型构成、
按日产出时间线。点任意类别，右侧即出现该类全部文件清单，可在
列表与预览图之间切换。每个文件都有预览（Quick Look 缩略图、
文本摘录）和“来自哪次对话”的来源卡片，一眼看懂。

## 架构

- **核心引擎（Python，跨平台）**——内容哈希身份（SHA-256)、
  sidecar 清单协议（`.guicang.json`）、版本链、状态机、去重、
  近似重复聚类（SimHash 候选 + Jaccard 复核）、FTS5 索引、
  存放位置扫描与复制、自动规则引擎。
- **macOS 原生应用（SwiftUI)**——常驻、开机自启，与引擎共用
  同一个 SQLite 登记库；所有数据库操作走后台队列，界面不卡。
- **算力分层**——本地算法优先，其次本地模型 / 自备端点，
  最后可选官方云（托管算力、同步、团队功能；Open Core 模式）。

在合成碎片语料上的实测（25,325 个文件：变体组、重复副本、
分片、噪声）：摄入约 2 秒（约 1.3 万文件／秒），增量重扫
0.4 秒，重复检出 375/375，变体聚类召回 99.6%／精度 100%，
分片归并 150/150，FTS 查询 0.5–6 毫秒。详见 `BENCH-20261022.md`。

## 快速开始（引擎 CLI)

```bash
python3 -m guicang.cli --db leanfile.db node-add mac ~/Documents --kind local
python3 -m guicang.cli --db leanfile.db scan mac
python3 -m guicang.cli --db leanfile.db build-previews
python3 -m guicang.cli --db leanfile.db infer-batches
python3 -m guicang.cli --db leanfile.db conversations
python3 -m guicang.cli --db leanfile.db autopilot-classify
python3 -m guicang.cli --db leanfile.db cleanup-plan
python3 -m guicang.cli --db leanfile.db bundle --latest      # 把一次对话打包交付
python3 -m guicang.cli --db leanfile.db protect-run --yes    # 给重要文件补验哈希的第二副本
python3 -m guicang.cli --db leanfile.db shards               # 列出分片组
python3 tests/test_core.py   # 以及 tests/test_*.py 其余测试套件
```

## macOS 应用

```bash
cd macos && ./build.sh   # 只需 Command Line Tools，无需完整 Xcode
open build/Guicang.app
```

界面语言跟随系统（中文 / 英文）。

## 安全契约

- 自动化永不硬删任何文件。清理 = 移入隔离区 + 完整日志，
  一条命令可恢复。
- 任何文件的最后一个副本、当前版本、正式版文件，
  清理规则一律碰不得。
- 推断得出的信息，处处标注“推断”，不冒充事实。

## 许可证

Apache License 2.0——见 `LICENSE`。

---

**English**: [README.md](README.md) · **Portal**: [sky791016.github.io/LeanFile](https://sky791016.github.io/LeanFile/)
