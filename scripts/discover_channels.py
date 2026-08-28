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
MIN_HITS = 1              # 何回ヒットしたら候補にするか
DAYS_BACK = 30

# ひらがな・カタカナ。漢字だけだと中国語と見分けがつかない。
KANA = re.compile(r"[ぁ-んァ-ヴｦ-ﾟ]")

# ジャンルを直接指定して探す。
#
# 以前は「今ランキングに載っているゲーム名」だけで検索していたが、これだと
# 既に上位にあるジャンルの配信者ばかりが増える。マイクラが多い日はマイクラの
# 配信者が増え、翌日さらにマイクラが上がる、という自分で自分を強化する状態に
# なってしまう。ジャンルを先に決めて広く薄く探すほうが、リスト全体としての
# 偏りは小さくなる。
GENRE_QUERIES = [
    "マインクラフト 実況 建築", "マイクラ 統合版 配信",
    "スト6 配信 ランクマ", "格ゲー 実況 対戦", "鉄拳8 配信", "スマブラSP 実況",
    "APEX 配信 ランク", "VALORANT 配信 実況", "FPS 実況 初心者",
    "ホラーゲーム 実況 絶叫", "フリーホラゲー 実況",
    "RPG 実況 縛りプレイ", "JRPG 実況 初見",
    "レトロゲーム 実況 スーファミ", "ファミコン 実況 クリア",
    "シミュレーションゲーム 実況 街づくり", "経営シミュレーション 実況",
    "音ゲー 配信 譜面", "太鼓の達人 配信",
    "レースゲーム 実況 タイムアタック",
    "パーティーゲーム 実況 大人数",
    "麻雀 配信 雀魂", "将棋 配信 実況", "カードゲーム 配信 対戦",
    "ソシャゲ 配信 ガチャ", "スマホゲーム 実況 攻略",
    "ノベルゲーム 実況 選択肢", "アドベンチャーゲーム 実況 考察",
    "サバイバルクラフト 実況 拠点", "オープンワールド 実況 探索",
    "パワプロ 実況 栄冠ナイン", "サッカーゲーム 実況 eFootball",
    "インディーゲーム 実況 新作", "ローグライク 実況 周回",
    "脱出ゲーム 実況 謎解き", "MMORPG 配信 レイド",
    "アクションゲーム 実況 高難度", "ソウルライク 実況 ボス",
    "パズルゲーム 実況 高難度", "協力プレイ 配信 コラボ",
    "個人勢 VTuber ゲーム配信", "ゲーム実況者 新人 生配信",
    "参加型 配信 視聴者参加", "初見プレイ 実況 女性",
    "ゲーム実況 生配信 少人数", "レビュー 実況 神ゲー",
]

# ランキングからも少しだけ拾う。ただし1〜9位ではなく中位から取る。
# 上位はもう十分にチャンネルが登録されていて、足しても偏りが増えるだけ。
RANK_FROM, RANK_TO, RANK_N = 10, 30, 6


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
    """直近の集計の中位に出てきたゲーム名。上位は避ける（偏りを増やすため）。"""
    site = read_json(DATA.parent / "site" / "data.json", None) or {}
    mid = site.get("ranking", [])[RANK_FROM - 1:RANK_TO]
    return [r["game"] for r in mid][:RANK_N]


def rotate(items, n):
    """日ごとに開始位置をずらす。何日か回すと全体を一周する。"""
    if not items:
        return []
    k = datetime.now(JST).timetuple().tm_yday * n % len(items)
    doubled = items[k:] + items[:k]
    return doubled[:n]


def main():
    yt = YouTube()
    ids, names = known_ids()
    log(f"登録済み: {len(ids)} チャンネル")

    # ジャンル中心。ランキング由来はごく少数に留める。
    n_rank = min(RANK_N, max(0, MAX_SEARCHES // 6))
    queries = rotate(GENRE_QUERIES, MAX_SEARCHES - n_rank) \
        + [f"{g} 実況" for g in recent_games()][:n_rank]
    queries = list(dict.fromkeys(queries))[:MAX_SEARCHES]
    if not queries:
        log("検索語が作れませんでした。")
        return
    after = (datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)
             ).strftime("%Y-%m-%dT%H:%M:%SZ")
    log(f"{len(queries)} 語で検索します（1語100ユニット / 上限 {MAX_SEARCHES} 語）")

    hits, found, skipped_lang = Counter(), {}, set()
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
            # このサイトは日本語圏の配信の流行を出すもの。動画タイトルに
            # かなが1文字も無いチャンネルは、ここで拾わない。
            # （検索の relevanceLanguage=ja は「並び順の目安」でしかなく、
            #   英語圏のチャンネルはこれだけでは弾けない）
            if not KANA.search(sn.get("title") or ""):
                skipped_lang.add(cid)
                continue
            hits[cid] += 1
            found[cid] = title
        if i % 10 == 0:
            log(f"  {i}/{len(queries)} 語 ／ 新顔 {len(found)} 件 ／ 使用 {yt.used}")

    cands = [(cid, found[cid], n) for cid, n in hits.most_common() if n >= MIN_HITS]
    log(f"見つかった新しいチャンネル: {len(cands)} 件 ／ 使用クォータ {yt.used}")
    log(f"日本語のタイトルが無いため見送ったチャンネル: {len(skipped_lang)} 件")
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
