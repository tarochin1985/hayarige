#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""判定があやしいものを、まとめて洗い出す。

    python scripts/check_matches.py

これまで誤検出は、たろちんさんが目で見つけて1件ずつ直していた。
「アイランド」「Match」「スイッチ」「プロジェクト」「F.E.A.R.」「Blood」──
どれも同じ形で、辞書に無い新作の名前の一部が、別の古いゲームの名前と
一致していた。報告が来るまで気づけないのは効率が悪いので、
同じ形をまとめて探す。

見ているのは2つ。

  1. 冒頭の【】の中身に対して、当たったゲーム名が短すぎるもの
     例: 【The Blood of Dawnwalker】の中の "Blood" だけが当たっている。
        括弧の中身はほぼ1つの固有名詞なので、その一部だけに当たるのは
        たいてい別のゲームの名前を拾っている。

  2. ゲーム名そのものはタイトルに出てこないのに、短い英字の別名で
     判定されているもの
     例: 「ラスト配信」→ Rust（別名「ラスト」）

出てきたものは、直し方が2通りある。
  ・正しいゲームが辞書に無い → data/aliases.json に足す
  ・別名が普通の言葉すぎる   → data/alias_blocklist.json に足す
"""
import collections
import glob
import json
import re
import sys

from common import DATA, log, read_json
import match as M

COVER = 0.55          # 括弧の中身のうち、何割に当たっていれば信用するか
MIN_LATIN_RATIO = 0.7  # 括弧の中身がどれだけ英字なら「英語の固有名詞」とみなすか


def titles():
    seen = {}
    for f in sorted(glob.glob(str(DATA / "daily" / "*.json"))):
        for v in (read_json(f, {}) or {}).get("videos", []):
            seen[v["id"]] = v
    return list(seen.values())


def latin_ratio(s):
    if not s:
        return 0.0
    return sum(1 for ch in s if ch.isascii() and ch.isalnum()) / len(s)


def main():
    idx = M.build_index()
    if len(idx.exact) < 500:
        log("ゲーム名辞書が空です。先にワークフロー2を辞書ありで動かしてください。")
        return 1
    vids = titles()
    log(f"実タイトル {len(vids)} 本を調べます")

    frag = collections.defaultdict(list)   # 1. 括弧の一部だけに当たった
    alias = collections.defaultdict(list)  # 2. 名前が出てこないのに当たった

    for v in vids:
        t = v["title"]
        g, how = M.extract(t, idx)
        if how != "dict":
            continue
        if M.compact(g) not in M.compact(t):
            alias[g].append(t)
        m = re.match(r"^[\s　#＃0-9]*[【『〖]([^】』〗]{1,60})[】』〗]", t)
        if not m:
            continue
        seg = m.group(1).strip()
        c = M.compact(seg)
        hit = idx.find(seg)
        if not hit or not c:
            continue
        if hit[1] / len(c) < COVER and latin_ratio(c) >= MIN_LATIN_RATIO:
            frag[(g, seg)].append(t)

    print("\n■ 冒頭の括弧の一部だけに当たっているもの（新作が辞書に無い可能性）")
    if not frag:
        print("   なし")
    for (g, seg), ts in sorted(frag.items(), key=lambda kv: -len(kv[1])):
        print(f"   {len(ts):3}本  判定={g!r}")
        print(f"        括弧の中身: {seg[:64]}")

    print("\n■ ゲーム名がタイトルに出てこないのに判定されたもの（多い順・上位15）")
    for g, ts in sorted(alias.items(), key=lambda kv: -len(kv[1]))[:15]:
        print(f"   {len(ts):3}本  {g[:40]}")
        print(f"        例: {ts[0][:66]}")
    print("\n※ 下のほうは略称（APEX、LOL、FF14 など）で正しいものが多い。"
          "\n   上のリストと、下で見覚えのないゲーム名が出ていないかを見る。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
