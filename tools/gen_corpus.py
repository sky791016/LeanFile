"""Generate a synthetic fragmented AI-production corpus with ground truth.

Fragment types planted (mirrors real AI production mess):
- base documents + lightly edited variants (near-duplicates)
- exact copies under ' (2)' style names in other folders
- shard sets: one document split into part01..03 files
- noise: thousands of unique small scraps (logs/json/md fragments)
Ground truth is written to <root>/_ground_truth.json (excluded from scan
by bench via a separate tree: truth lives OUTSIDE the scanned root).
"""
import json
import os
import random
import sys

VOCAB = [f"w{i:04d}" for i in range(2000)]


def doc_text(rng, n=130):
    return "标题 doc\n" + " ".join(rng.choice(VOCAB) for _ in range(n)) + "\n"


def mutate(rng, text, rate=0.06):
    toks = text.split(" ")
    k = max(1, int(len(toks) * rate))
    for _ in range(k):
        toks[rng.randrange(len(toks))] = rng.choice(VOCAB)
    return " ".join(toks)


def main(root, truth_path):
    rng = random.Random(42)
    os.makedirs(root, exist_ok=True)
    truth = {"variant_groups": [], "shard_groups": [], "copy_pairs": []}
    bases = 1500
    for i in range(bases):
        text = doc_text(rng)
        rel = f"projects/p{i%20}/doc-{i:04d}.md"
        p = os.path.join(root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(text)
        group = [rel]
        for v in (1, 2):
            vrel = f"projects/p{i%20}/doc-{i:04d}-v{v}.md"
            with open(os.path.join(root, vrel), "w") as f:
                f.write(mutate(rng, text))
            group.append(vrel)
        truth["variant_groups"].append(group)
        if i % 4 == 0:  # exact copy elsewhere
            crel = f"downloads/doc-{i:04d} (2).md"
            cp = os.path.join(root, crel)
            os.makedirs(os.path.dirname(cp), exist_ok=True)
            with open(cp, "w") as f:
                f.write(text)
            truth["copy_pairs"].append([rel, crel])
        if i % 10 == 0:  # shards of the same document
            parts = []
            toks = text.split(" ")
            third = len(toks) // 3
            for pi in range(3):
                srel = f"shards/s{i:04d}_part{pi+1:02d}.md"
                sp = os.path.join(root, srel)
                os.makedirs(os.path.dirname(sp), exist_ok=True)
                with open(sp, "w") as f:
                    f.write(" ".join(toks[pi * third:(pi + 1) * third]))
                parts.append(srel)
            truth["shard_groups"].append(parts)
    noise = 20000
    for i in range(noise):
        kind = i % 3
        if kind == 0:
            rel, ext, body = f"scraps/log-{i:05d}.log", "log", f"log line {i} {rng.random()}"
        elif kind == 1:
            rel, ext, body = f"scraps/frag-{i:05d}.json", "json", json.dumps({"i": i, "x": rng.random()})
        else:
            rel, ext, body = f"scraps/note-{i:05d}.md", "md", "随手记 " + " ".join(rng.choice(VOCAB) for _ in range(12))
        p = os.path.join(root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(body)
    with open(truth_path, "w") as f:
        json.dump(truth, f)
    total = sum(len(files) for _, _, files in os.walk(root))
    print(f"corpus at {root}: {total} files")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
