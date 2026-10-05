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
    rows = [x for x in find_series(videos, idx) if len(x[1]) >= a.min]
    print(f"のべ {len(videos)} 本を見ました"
          f"（{'全部' if a.days <= 0 else f'直近{a.days}日'}）")
    if not rows:
        print("候補はありません。")
        return 0
    print(f"候補 {len(rows)} 件。**半分以上は空振りです。**"
          "判断は data/辞書の直し方.md の3章。\n")
    for (al, q, g), vs in rows:
        print(f"「{al}」＋「{q}」 → いま {g} : "
              f"{len(vs)}本 / {len({v[1] for v in vs})}ch")
        for t, ch in vs[:2]:
            print(f"      {t[:88]}  ({ch})")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
