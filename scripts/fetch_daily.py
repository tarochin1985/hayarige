#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""毎日の収集。対象チャンネルの新着動画を取ってきて保存する。

クォータの使い方：
  - 活発な上位チャンネルは毎日、それ以外は曜日で分けて週1回
  - 新着一覧は1チャンネル1ユニット、動画の詳細は50本で1ユニット
"""
import os
from datetime import datetime, timedelta, timezone
from common import (YouTube, QuotaExhausted, DATA, JST, log,
                    read_json, write_json, today, is_countable)

# 毎回見るチャンネル数（登録者順）。ここに入らなかったチャンネルは曜日で分けて週1回。
# 1回の消費は「チャンネル数 × 1.2」ポイント。1日4回なので、
#   （DAILY_TOP + (登録数 - DAILY_TOP) / 7） × 1.2 × 4 が1日の消費。
# 1,200なら、登録2,000件でも約6,300／日で上限9,000に収まる。
# 登録数を増やしていくときは、ここを上げないと大半が週1回しか見られなくなる。
DAILY_TOP = int(os.environ.get("DAILY_TOP", "1200"))
LOOKBACK_HOURS = 48      # 何時間前までの動画を対象にするか


def pick_targets():
    chans = read_json(DATA / "channels_enriched.json", []) or []
    manual = read_json(DATA / "channels_manual.json", {}) or {}   # {channel_id: "残す"/"外す"}
    live = []
    for c in chans:
        cid = c.get("channel_id")
        if not cid:
            continue
        m = manual.get(cid)
        if m == "外す":
            continue
        if m != "残す" and str(c.get("auto", "")).startswith("外す"):
            continue
        live.append(c)
    live.sort(key=lambda c: -(c.get("subscribers") or 0))

    daily = live[:DAILY_TOP]
    rest = live[DAILY_TOP:]
    bucket = datetime.now(JST).weekday()          # 0..6
    weekly = [c for i, c in enumerate(rest) if i % 7 == bucket]
    log(f"対象: 毎日 {len(daily)} 件 + 今日の当番 {len(weekly)} 件 "
        f"（登録済み {len(live)} 件）")
    return daily + weekly


def main():
    yt = YouTube()
    targets = pick_targets()
    if not targets:
        log("対象チャンネルがありません。先に enrich_channels.py を実行してください。")
        return

    # 以前は「一度見た動画は二度と取らない」ようにしていたが、これをやめた。
    # 理由が2つある。
    #   1. その日のファイルが「前回の実行から今までに増えた分」だけになり、
    #      実行した時刻によって『1日の本数』が激しく変わってしまっていた。
    #   2. 配信直後に取った再生数のまま固定され、伸びが反映されなかった。
    # 動画の詳細取得は50本で1ポイントしか使わないので、毎回取り直しても安い。
    new_ids, owner = [], {}
    for n, c in enumerate(targets, 1):
        pl = c.get("uploads_playlist")
        if not pl:
            # uploads プレイリストIDはチャンネルIDの3文字目を U に変えたもの
            pl = "UU" + c["channel_id"][2:]
        try:
            r = yt.uploads(pl, 10)
        except QuotaExhausted as e:
            log(f"クォータ上限のため {n} 件目で打ち切ります: {e}")
            break
        except Exception as e:
            log(f"  取得失敗 {c.get('title', c['name'])}: {str(e)[:120]}")
            continue
        for it in r.get("items", []):
            vid = it["contentDetails"]["videoId"]
            if vid in owner:
                continue
            new_ids.append(vid)
            owner[vid] = c
        if n % 100 == 0:
            log(f"  {n}/{len(targets)} 件 ／ 使用クォータ {yt.used}")

    log(f"詳細を取る候補 {len(new_ids)} 本 ／ 使用クォータ {yt.used}")

    # YouTubeが返す publishedAt は "2026-08-27T01:00:00Z" というUTC表記。
    # 比べる相手も同じ形にしないと、9時間ずれた範囲で切ってしまう。
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
              ).strftime("%Y-%m-%dT%H:%M:%SZ")
    videos, skipped = [], 0
    for i in range(0, len(new_ids), 50):
        try:
            r = yt.videos(new_ids[i:i + 50])
        except QuotaExhausted:
            log("クォータ上限のため動画詳細の取得を打ち切ります")
            break
        for v in r.get("items", []):
            pub = v["snippet"]["publishedAt"]
            if pub < cutoff:
                continue
            dur = (v.get("contentDetails") or {}).get("duration", "")
            # Shortsと切り抜きはランキングに数えない
            if not is_countable(v["snippet"]["title"], dur):
                skipped += 1
                continue
            c = owner.get(v["id"], {})
            live = v.get("liveStreamingDetails") or {}
            videos.append({
                "id": v["id"],
                "title": v["snippet"]["title"],
                "published": pub,
                "channel_id": v["snippet"]["channelId"],
                "channel": v["snippet"]["channelTitle"],
                "affiliation": c.get("affiliation", ""),
                "views": int(v["statistics"].get("viewCount", 0) or 0),
                "is_live": bool(live.get("actualStartTime")),
                "thumb": (v["snippet"]["thumbnails"].get("medium") or {}).get("url", ""),
            })

    write_json(DATA / "daily" / f"{today()}.json",
               {"date": today(), "quota_used": yt.used,
                "channels_checked": len(targets), "videos": videos})
    log(f"保存しました: data/daily/{today()}.json （{len(videos)} 本 ／ Shorts・切り抜き {skipped} 本を除外）")
    log(f"本日の使用クォータ: {yt.used}")


if __name__ == "__main__":
    main()
