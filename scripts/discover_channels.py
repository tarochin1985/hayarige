#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""まだ登録していないゲーム配信チャンネルを探す。

やり方は単純で、「今ランキングに載っているゲーム名」でYouTubeを検索し、
出てきた動画の投稿者のうち、まだ知らないチャンネルを拾う。
名前のリストを人が集めるより、実際にそのゲームを配信している人が直接見つかる。

検索は1回100ユニットと高いので、回数を上限で縛る。
拾ったチャンネルは channels.tsv に足すだけ。残すか外すかの判断は
enrich_channels.py が（登録者数・最終投稿日・ゲーム動画率を見て）行う。
"""
import csv
import os
import re
from collections import Counter
from datetime import datetime, timedelta, timezone

from common import (YouTube, QuotaExhausted, DATA, JST, log,
                    read_json, write_json, today)

CH_TSV = DATA / "channels.tsv"
OUT_CSV = DATA / "channels_discovered.csv"

MAX_SEARCHES = int(os.environ.get("MAX_SEARCHES", "40"))   # 40回 = 4,000ユニット
GAMES_FROM_RANKING = 25
MIN_HITS = 1              # 何回ヒットしたら候補にするか
DAYS_BACK = 30

# ゲーム名だけだと海外チャンネルも混ざるので、日本語の配信用語も混ぜる
GENERIC = [
    "ゲーム実況 生配信", "初見プレイ 実況", "参加型 配信 ゲーム",
    "VTuber ゲーム配信", "個人勢 VTuber 実況", "ゲーム実況者 新人",
]


def known_ids():
    ids, names = set(), set()
    if CH_TSV.exists():
        with open(CH_TSV, encoding="utf-8") as f:
            for r in csv.DictReader(f, delimiter="\t"):
                cid = (r.get("channel_id") or "").strip()
                if cid:
                    ids.add(cid)
                names.add((r.get("name") or "").strip())
    for c in read_json(DATA / "channels_enriched.json", []) or []:
        if c.get("channel_id"):
            ids.add(c["channel_id"])
    return ids, names


def recent_games():
    """直近の集計に出てきたゲーム名。検索語として一番効率がいい。"""
    site = read_json(DATA.parent / "site" / "data.json", None) or {}
    return [r["game"] for r in site.get("ranking", [])[:GAMES_FROM_RANKING]]


def main():
    yt = YouTube()
    ids, names = known_ids()
    log(f"登録済み: {len(ids)} チャンネル")

    queries = [f"{g} 実況" for g in recent_games()] + GENERIC
    if not queries:
        log("検索語が作れませんでした。先に3番（毎日の更新）を動かしてください。")
        return
    queries = queries[:MAX_SEARCHES]
    after = (datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)
             ).strftime("%Y-%m-%dT%H:%M:%SZ")
    log(f"{len(queries)} 語で検索します（1語100ユニット / 上限 {MAX_SEARCHES} 語）")

    hits, found = Counter(), {}
    for i, q in enumerate(queries, 1):
        try:
            r = yt.search_videos(q, published_after=after)
        except QuotaExhausted as e:
            log(f"クォータ上限のため {i} 語目で打ち切ります: {e}")
            break
        except Exception as e:
            log(f"  検索失敗 {q}: {str(e)[:100]}")
            continue
        for it in r.get("items", []):
            sn = it.get("snippet") or {}
            cid = sn.get("channelId")
            title = (sn.get("channelTitle") or "").strip()
            if not cid or cid in ids or not title:
                continue
            hits[cid] += 1
            found[cid] = title
        if i % 10 == 0:
            log(f"  {i}/{len(queries)} 語 ／ 新顔 {len(found)} 件 ／ 使用 {yt.used}")

    cands = [(cid, found[cid], n) for cid, n in hits.most_common() if n >= MIN_HITS]
    log(f"見つかった新しいチャンネル: {len(cands)} 件 ／ 使用クォータ {yt.used}")
    if not cands:
        return

    # 同じ表示名が既にある場合は、別チャンネルでも紛らわしいので印を付ける
    with open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["name", "channel_id", "ヒット数", "既存と同名", "URL"])
        for cid, title, n in cands:
            w.writerow([title, cid, n, "○" if title in names else "",
                        f"https://www.youtube.com/channel/{cid}"])

    # channels.tsv に追記する。所属は空（あとで手で入れてもいいし、無くても動く）
    with open(CH_TSV, "a", encoding="utf-8", newline="") as f:
        for cid, title, n in cands:
            f.write(f"{title}\t{cid}\t\n")

    log(f"channels.tsv に {len(cands)} 件を追記しました")
    log(f"一覧: data/channels_discovered.csv")
    log("このあと enrich_channels が、更新が止まっているチャンネルや"
        "ゲーム動画のないチャンネルを自動で外します。")


if __name__ == "__main__":
    main()
