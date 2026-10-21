<p align="center">
  <img src="brand/app-icon-1024.png" width="128" alt="LeanFile app icon">
</p>

<h1 align="center">LeanFile</h1>

<p align="center">
  <strong>Every file your AI makes — gathered, deduplicated, organized by conversation, and findable in milliseconds.</strong>
</p>

<p align="center">
  <a href="README.zh-CN.md">简体中文</a> ·
  <a href="https://sky791016.github.io/LeanFile/">Portal</a> ·
  <a href="#quick-start-engine-cli">Quick start</a> ·
  <a href="LICENSE">License</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/license-Apache%202.0-blue" alt="License: Apache 2.0">
  <img src="https://img.shields.io/badge/platform-macOS%2014%2B-0B2B4B" alt="Platform: macOS 14+">
  <img src="https://img.shields.io/badge/core-Python%203-3776AB" alt="Core: Python 3">
  <img src="https://img.shields.io/badge/UI-SwiftUI-orange" alt="UI: SwiftUI">
</p>

AI tools now produce files faster than any folder system can absorb:
drafts, variants, renders, shards — thousands of near-identical files
scattered across machines and NAS drives. LeanFile is the asset layer that
sits on top of your files and quietly keeps them in order.

> LeanFile is part of the Lean family by Kai Shi — alongside the
> Lean Data Methodology, Lean AI and LeanFDE: lean thinking applied
> to the file chaos of the AI era. (Internal codename: `MM1031`.)

## What it does — five outcomes, not process data

Users don't care about version graphs. They care that:

1. **Duplicates disappear automatically** — identical content keeps one
   best copy; extras are quarantined (never hard-deleted), restorable
   in one click.
2. **Files classify themselves** — every file gets a category and an
   importance class: *protected / keep / ephemeral*.
3. **Full-text search actually finds things** — SQLite FTS5 over
   document bodies, millisecond queries at 10k+ files.
4. **Important files can't be lost** — protected files are monitored
   for single-copy risk and replicated across storage nodes.
5. **Junk expires by rule** — you set the rules (keep process versions
   N days, quarantine retention, …); LeanFile executes them, always via
   quarantine first, always logged, always reversible.
6. **Conversations pack themselves for handover** — one click bundles
   what a conversation produced (each asset's latest version from that
   conversation) into a clean folder with a manifest.
7. **Shard groups are visible** — files that are really fragments of
   one whole (part files, sequence splits) are detected and listed as
   groups, so pieces can be reunited instead of scattered.

## Scenarios — ten everyday messes

**1. The article with twelve “final” versions.**
*Pain:* Twelve rounds of AI edits, twelve saves: final, real-final,
final-v2… When it's time to send, even you can't say which one counts —
and the nightmare is sending the old draft.
*Fix:* Exactly one Final, ever. Every earlier take stays one click away
in the version line, but “the current version” has only one answer.

**2. Video production chaos.**
*Pain:* A seven-minute film is hundreds of files — drone originals,
voice takes a01–a35, renders v1–v9, a stabilized cut, a light cut…
Folders can't tell you which one is *the* film, and hand-picking files
for delivery means one missed file ruins the handover.
*Fix:* Files group themselves by the work session; shards are detected
as groups; one click bundles each file's best version into a clean
folder with a manifest. No more counting by hand.

**3. Client deliverables.**
*Pain:* A proposal revised over weeks, with different versions living
in chat threads, email and meeting notes. The client asks “did that
number change later?” and you need half an hour to answer safely —
while fearing you'll send the internal-discussion version.
*Fix:* One unambiguous Final, with its source conversation attached.
The bundle you export is exactly what the client receives; internal
process versions never slip in.

**4. AI pair-programming sprawl.**
*Pain:* Two AI coding tools take turns on one project; temp scripts,
experiments and generated samples pile up. You dare not commit, dare
not delete, and nobody can say which files are the real code.
*Fix:* Process files are classed *ephemeral* and expire by rule into a
restorable quarantine; real code stays classified and full-text
searchable.

**5. Data-analysis runs.**
*Pain:* One analysis exports forty CSVs and charts, all named
data_final(3).xlsx. Three days later, reusing one table means opening
every file by hand.
*Fix:* Spreadsheets classify themselves; full-text search finds the
table by what's *in* it; duplicate exports dedup automatically.

**6. The book manuscript.**
*Pain:* Chapters polished by AI dozens of times, a dozen versions of
each scattered across folders. When the editor asks for the latest
chapter, you guess from memory and timestamps.
*Fix:* Every chapter's version chain stays legible; any chapter's
latest draft packs in one click; the submitted draft becomes the one
Final and can't be confused again.

**7. Bid & proposal war-room.**
*Pain:* Dozens of attachments, many hands, a hard deadline. Two fears
dominate: submitting something that isn't the final version, and a key
attachment existing on exactly one laptop whose disk is about to die.
*Fix:* One Final per document; single-copy important files raise an
alarm and get a hash-verified second copy in one click.

**8. AI image batches.**
*Pain:* One prompt, twenty images, all named image_4839.png. Picking
in Finder is roulette, and afterwards the folder is full of duplicates
and rejects.
*Fix:* A preview-thumbnail grid shows all of them at once; pick the
Final in place; duplicates merge automatically, rejects expire by rule.

**9. Family media vault.**
*Pain:* A decade of photos and drone footage across a laptop, a
desktop and a NAS: the same content stored three times over — while
the irreplaceable originals exist exactly once. One dead disk is the
family archive gone.
*Fix:* One registry sees all three locations; byte-level dedup frees
space; irreplaceable originals are classed *protected* and get
verified second copies.

**10. The 3 a.m. “where is that file?”**
*Pain:* On deadline at 3 a.m. you remember an AI wrote the perfect
paragraph — or built the perfect table — in some chat last month. You
remember roughly what it said, never what it's called. Filename search
finds nothing; chat history swallows the evening.
*Fix:* Search by what the file *says*, or open the conversation that
made it and see everything it produced. Milliseconds, not an evening
of digging.

## Organized by conversation

You remember a file by *the chat that produced it*, not by its folder.
LeanFile organizes files under the LLM conversation / work session that
created them: registrations carry conversation metadata (tool, model,
title), and legacy files are reconstructed into sessions by project
folder + time-window analysis — honestly labeled *inferred*, never
presented as fact.

## Dashboard first

The macOS app opens on a dashboard: totals, capacity, category and
type breakdowns, production-by-day timeline. Click any category and
the right pane lists its files — switchable between list view and a
preview-thumbnail grid. Full previews (Quick Look thumbnails, text
excerpts) and source-conversation cards make every file legible at a
glance.

## Screenshots

Real captures from the running app (the first user's live registry:
2,056 files):

![Dashboard](docs/img/shots/en/pub-dashboard.png)
*Dashboard — totals, category/type breakdowns, production by day.*

![Drill-down](docs/img/shots/en/pub-drill.png)
*Click a category and its files appear on the right (drill-down).*

![A conversation's files](docs/img/shots/en/pub-conversation.png)
*One conversation's output, with one-click bundle export.*

![Auto rules](docs/img/shots/en/pub-rules.png)
*Auto rules — off by default; you switch on what LeanFile may do.*

## Architecture

- **Core engine (Python, platform-independent)** — content-hash
  identity (SHA-256), sidecar manifest protocol (`.guicang.json`),
  version chains, state machine, dedup, near-duplicate clustering
  (SimHash candidates + Jaccard verification), FTS5 indexing,
  storage-node scanning and replication, autopilot rules engine.
- **Native macOS app (SwiftUI)** — resident, launch-at-login,
  Finder-companion UI reading the same SQLite registry; all database
  work runs off the main thread.
- **Compute tiers** — local algorithms first, local models / BYO
  endpoints next, optional official cloud for hosted compute,
  sync and team features (open-core model).

Measured on a synthetic fragmented corpus (25,325 files: variant
groups, duplicates, shards, noise): ingest ≈ 2 s (~13k files/s),
incremental rescan 0.4 s, duplicate detection 375/375, variant
clustering 99.6% recall at 100% precision, shard reassembly 150/150,
FTS queries 0.5–6 ms. See `BENCH-20261022.md`.

## Quick start (engine CLI)

```bash
python3 -m guicang.cli --db leanfile.db node-add mac ~/Documents --kind local
python3 -m guicang.cli --db leanfile.db scan mac
python3 -m guicang.cli --db leanfile.db build-previews
python3 -m guicang.cli --db leanfile.db infer-batches
python3 -m guicang.cli --db leanfile.db conversations
python3 -m guicang.cli --db leanfile.db autopilot-classify
python3 -m guicang.cli --db leanfile.db cleanup-plan
python3 -m guicang.cli --db leanfile.db bundle --latest      # pack a conversation for handover
python3 -m guicang.cli --db leanfile.db protect-run --yes    # verified 2nd copies of important files
python3 -m guicang.cli --db leanfile.db shards               # list shard groups
python3 tests/test_core.py   # and the other tests/test_*.py suites
```

## macOS app

```bash
cd macos && ./build.sh   # Command Line Tools only, no full Xcode
open build/Guicang.app
```

The UI follows your system language (Chinese / English).

## Safety contract

- Nothing is ever hard-deleted by automation. Cleanup moves files to
  a quarantine area with a full log; restore is one command.
- The last copy of anything, the current version of anything, and
  final/published files are untouchable by cleanup rules.
- Inferred information is labeled *inferred* everywhere it appears.

## License

Apache License 2.0 — see `LICENSE`.

---

**中文版**：[README.zh-CN.md](README.zh-CN.md) · **门户网站**：[sky791016.github.io/LeanFile](https://sky791016.github.io/LeanFile/)
