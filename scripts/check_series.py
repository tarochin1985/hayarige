#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""シリーズ名が続編を吸っていないかを探す見張り。

    python3 scripts/check_series.py            # 直近30日
    python3 scripts/check_series.py --days 0   # 記録のある全部（5分くらい）

なぜ作ったか（2026-10-05 たろちんさん）
--------------------------------------
    > 今日のランキング、トルネコの大冒険にトルネコの大冒険2と3が
    > 巻き込まれてるのを観測。また、「龍が如く」に龍が如く極3や
    > 龍が如く維新！極などが巻き込まれている。
    > こういうシリーズ絡みのエラーがまだまだ多そう

そのとおりで、全タイトルを調べたら104本が別の作品に入っていた。
**「辞書の直し方」3章に文章で書いてあっても、見つける手段が無かった。**
`find_misses()` は「どこにも入っていない配信」を探す見張りで、
**こちらは逆に「入っているが、入り先が間違っている配信」を探す。**

探し方
------
`【】『』〖〗` の中（＝配信者がゲーム名を書く場所）だけを見て、
**登録済みの別名のすぐ後ろに短い修飾語が付いていて、その長い形が
辞書に無い**ものを挙げる。たとえばこうなる。

    「トルネコの大冒険」＋「2」 → いま Torneko's ... Classic HD : 9本

カタログ側から探すことはできない。『ルイージマンション3』のように、
カタログには英語名しか無いことが多く、**日本語の別名と日本語の続編名を
突き合わせられない**（だから穴が開いている）。配信タイトルのほうから
見るしかない。

出てくるものは**候補で、半分以上は空振り**である。
`2026`（年）`113`（話数）`2.0`（版）`49日間` `99階` のように、
数字が続くのは続編とは限らない。空振りを減らすために STOP と VER で
よくある形を外してあるが、**最後は人が1件ずつ見る。** 判断の仕方は
data/辞書の直し方.md の3章に書いてある。
"""
import argparse
import collections
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import match as M                                     # noqa: E402
from common import DATA, read_json                    # noqa: E402

# ゲーム名が書かれる場所。タイトル全文から拾うと空振りが増える
BRACKET = re.compile(r"[【『〖「《≪\[]([^】』〗」》≫\]]{2,60})[】』〗」》≫\]]")
# 別名の後ろに来てよい「続編らしい字」
SUFFIX = r"[0-9ivx極維新改外伝zゼロ！!・:：]{1,8}"
# その後ろがこれなら、数え上げであって続編ではない
STOP = re.compile(
    r"^(?:周年|回目|日間|階|タイトル|交流戦|人|年|月|日|名|戦|勝|位|％|%|"
    r"時間|分|話|章|期|体|面|問|連|枚|本|回|地区|県|都|府|個|軍|位目)")
VER = re.compile(r"^[vV]")          # v3.1 のような版番号
# 修飾語の直後がこれなら、単語の途中を切っただけ。
# これを入れるまで genshin＋「i」（impact）や
# dead by daylight＋「ロ」（ローモバ）が毎回出ていた。
MIDWORD = re.compile(r"^[a-zA-Z\u3040-\u30ff]")
# 「ダビスタ2」＋「026」のように、足すと西暦になるもの
YEAR = re.compile(r"(?:19|20)\d{2}$")


def unique_videos(days):
    """動画ID → (題名, チャンネル)。同じ動画が何日も出るので畳む。"""
    out, files = {}, sorted((DATA / "daily").glob("*.json"))
    if days > 0:
        files = files[-days:]
    for f in files:
        for v in (read_json(f, {}) or {}).get("videos", []):
            out[v["id"]] = (v.get("title") or "", v.get("channel") or "")
    return out


def find_series(videos, idx):
    al = read_json(DATA / "aliases.json", {}) or {}
    known = set(idx.exact)
    for lst in idx.bucket.values():
        for c, _sp, _g, _p in lst:
            known.add(c)
    names = sorted({a for g, v in al.items() for a in [g] + list(v)
                    if len(M.compact(a)) >= 3}, key=len, reverse=True)
    if not names:
        return []
    pat = re.compile("(" + "|".join(re.escape(M.norm(a)) for a in names)
                     + r")[\s　]*(" + SUFFIX + ")")
    mine = {g: {M.compact(x) for x in v} | {M.compact(g)}
            for g, v in al.items()}
    # 調べたうえで「いまの入り先で正しい」と決めた組。
    # これが無いと、空振りが毎回同じ顔で並び、人が読むのをやめてしまう
    ok = set((read_json(DATA / "series_ok.json", {}) or {}).get("組", []))
    ok |= {f"{M.norm(x.split('|')[0])}|{x.split('|')[1]}"
           for x in list(ok) if "|" in x}
    hits = collections.defaultdict(list)
    for t, ch in videos.values():
        g, how = M.extract(t, idx, fallback=True)
        if how != "dict":
            continue
        for inner in BRACKET.findall(t):
            n = M.norm(inner)
            for m in pat.finditer(n):
                a, q = m.group(1), m.group(2).strip()
                if not q or VER.match(q):
                    continue
                rest = n[m.end():]
                if STOP.match(rest) or MIDWORD.match(rest):
                    continue
                if YEAR.search(M.compact(a + q)):
                    continue              # 2026 は続編ではなく年
                if M.compact(a + q) in known:
                    continue              # 続編も登録済み。問題なし
                if M.compact(a) not in mine.get(g, set()):
                    continue              # その別名で入ったのではない
                if f"{a}|{q}" in ok or f"{M.norm(a)}|{q}" in ok:
                    continue              # 調べたうえで「正しい」と決めた組
                hits[(a, q, g)].append((t, ch))
    return sorted(hits.items(), key=lambda x: -len(x[1]))


def find_longer(videos, idx):
    """**題の中に、入り先の名前より長い「別のゲームの名前」が書いてある**ものを探す。

    なぜ要るか（2026-10-11 たろちんさん）
    ------------------------------------
        > ぽちかのさんのトルネコ3の配信4本が、「トルネコの大冒険
        > ちょっとステキなリマスター」（1作目）の行に入っています。

        【トルネコ最新作】トルネコ3mod 魔物の心髄　56F～
          ↑ 冒頭の括弧の「トルネコ」で1作目に入った
                    ↑ 題のここに「トルネコ3」と書いてある

    `find_series()` は**括弧の中で「別名＋続編らしい字」**を探す見張りなので、
    これは引っかからなかった。「最新作」は続編らしい字ではないし、
    正しい名前は括弧の外に書かれている。

    ここで見るのは1つだけ。**入り先の別名が、別のゲームの別名の「頭」に
    なっていて、その長いほうが題の中に書かれている**とき。
    「トルネコ」は「トルネコ3」の頭で、題に「トルネコ3」がある。だから挙がる。

    頭になっていない組は見ない。『スプラトゥーン3』の題に `SurgeTown` が
    出てきても、頭ではないので挙がらない（別のゲームの話をしているだけ）。
    """
    al = read_json(DATA / "aliases.json", {}) or {}
    # ゲーム → 詰めた形の別名（行の名前そのものも別名として入る）
    mine = {g: {M.compact(x) for x in list(v) + [g] if len(M.compact(x)) >= 3}
            for g, v in al.items()}
    # 詰めた形 → それを持つゲーム
    owner = collections.defaultdict(set)
    for g, cs in mine.items():
        for c in cs:
            owner[c].add(g)
    ok = set((read_json(DATA / "series_ok.json", {}) or {}).get("組", []))
    hits = collections.defaultdict(list)
    for t, ch in videos.values():
        g, how = M.extract(t, idx, fallback=True)
        if how != "dict" or g not in mine:
            continue
        tc = M.compact(t)
        # その題の中にある、入り先の別名のうちいちばん長いもの＝勝った別名
        got = [c for c in mine[g] if c in tc]
        if not got:
            continue
        won = max(got, key=len)
        for c2, gs in owner.items():
            if len(c2) <= len(won) or not c2.startswith(won):
                continue
            if c2 not in tc:
                continue
            for g2 in gs:
                if g2 == g or f"{g}>>{g2}" in ok:
                    continue
                hits[(won, c2, g, g2)].append((t, ch))
    return sorted(hits.items(), key=lambda x: -len(x[1]))


def main():
    ap = argparse.ArgumentParser(
        description="シリーズ名が続編を吸っていないかを探す")
    ap.add_argument("--days", type=int, default=30,
                    help="直近いくつの記録を見るか。0 で全部（既定30）")
    ap.add_argument("--min", type=int, default=3,
                    help="この本数以上のものだけ出す（既定3）。"
                         "1 にすると1本のものまで全部出る")
    a = ap.parse_args()

    idx = M.build_index()
    videos = unique_videos(a.days)
    print(f"のべ {len(videos)} 本を見ました"
          f"（{'全部' if a.days <= 0 else f'直近{a.days}日'}）")

    rows = [x for x in find_series(videos, idx) if len(x[1]) >= a.min]
    print()
    print("■ 括弧の中が「別名＋続編らしい字」になっているもの")
    if not rows:
        print("  候補はありません。")
    else:
        print(f"  候補 {len(rows)} 件。**半分以上は空振りです。**"
              "判断は data/辞書の直し方.md の3章。\n")
        for (al, q, g), vs in rows:
            print(f"「{al}」＋「{q}」 → いま {g} : "
                  f"{len(vs)}本 / {len({v[1] for v in vs})}ch")
            for t, ch in vs[:2]:
                print(f"      {t[:88]}  ({ch})")
            print()

    long_rows = [x for x in find_longer(videos, idx) if len(x[1]) >= a.min]
    print()
    print("■ 題の中に、入り先より長い別のゲーム名が書いてあるもの")
    if not long_rows:
        print("  候補はありません。")
        return 0
    print(f"  候補 {len(long_rows)} 件。**こちらは空振りが少ない。**"
          "長いほうが正しいことがほとんど。\n")
    for (won, c2, g, g2), vs in long_rows:
        print(f"「{won}」で {g} に入っているが、題に「{c2}」（{g2}）がある : "
              f"{len(vs)}本 / {len({v[1] for v in vs})}ch")
        for t, ch in vs[:2]:
            print(f"      {t[:88]}  ({ch})")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
