#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""毎日の収集。対象チャンネルの新着動画を取ってきて保存する。

クォータの使い方：
  - 活発な上位チャンネルは毎日、それ以外は曜日で分けて週1回
  - 新着一覧は1チャンネル1ユニット、動画の詳細は50本で1ユニット
"""
import os
from datetime import datetime, timedelta, timezone
from common import (YouTube, QuotaExhausted, DATA, JST, log, QUOTA_LIMIT,
                    read_json, write_json, today, is_countable, iso_seconds)

# 毎回見るチャンネル数（登録者順）。ここに入らなかったチャンネルは曜日で分けて週1回。
# 1回の消費は「チャンネル数 × 1.2」ポイント。1日の実行回数を R とすると、
#   （DAILY_TOP + (登録数 - DAILY_TOP) / 7） × 1.2 × R が1日の消費。
#
# 2026-08-29に1日4回から2回に減らした（.github/workflows/3-daily.yml に経緯）。
# 回数が減った分ここを上げられる。2,000なら、登録2,500件・2回/日で
# 約5,000ポイント。残りをチャンネル探索（2番）に回せる。
# ここを上げないと、増やしたチャンネルの大半が週1回しか見られない。
DAILY_TOP = int(os.environ.get("DAILY_TOP", "2000"))
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

    # ---- 今日すでに取った分を読む（2026-09-26に入れた） ----
    #
    # なぜ要るか。この日、サイトに出るゲームが229種から120種まで落ちた。
    # 原因は「1日のうちに『3. 毎日の更新』を4回回してクォータを使い切り、
    # **5回目が0本で保存して、それまでに取れていた2,442本を上書きした**」。
    #   09-25 19:16 ／ 09-26 07:14 ／ 12:04 ／ 14:18 … 4回で約9,600
    #   09-26 15:00 … 171使ったところで上限。動画0本で保存 ← ここで消えた
    #
    # **取れなかったことより、取れていたものを消したことのほうが悪い。**
    # 直し方は2つ入れた。
    #   (1) 上書きせず**混ぜる**（下の write のところ）
    #   (2) 使い切りそうなら**取りに行かない**。0本で保存する事故が起きない
    #
    # クォータは日本時間の16時（太平洋時間の0時）に戻る。
    day_path = DATA / "daily" / f"{today()}.json"
    prev = read_json(day_path, None) or {}
    kept = {v["id"]: v for v in (prev.get("videos") or []) if v.get("id")}
    spent = int(prev.get("quota_today") or prev.get("quota_used") or 0)
    runs = int(prev.get("runs") or (1 if prev else 0))
    # 1回の取得にかかるおよその量。対象チャンネル数 × 1.2 に少し余裕を足す
    need = int(len(targets) * 1.2) + 100
    if kept and spent + need > QUOTA_LIMIT:
        log(f"今日はすでに {runs} 回取得していて、使ったクォータは約 {spent} です。"
            f"あと {need} ぶんの余裕が無いので、今回は取りに行きません。")
        log(f"すでに取れている {len(kept)} 本をそのまま使います。"
            "クォータは日本時間の16時に戻ります。それ以降に"
            "『3. 毎日の更新』をもう一度回すと取り直せます。")
        write_json(day_path, dict(prev, runs=runs + 1, skipped=True))
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
            # 縦横比。1より大きければ縦長。いまは記録するだけで、
            # これを理由に落とすことはしていない。実際の数字を数日ぶん見てから
            # 決めたいので、まず材料を残す。
            pl = v.get("player") or {}
            w, hgt = pl.get("embedWidth"), pl.get("embedHeight")
            shape = round(float(hgt) / float(w), 2) if w and hgt else None
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
                "secs": iso_seconds(dur),
                "shape": shape,
            })

    # 今日すでに取れていた分と混ぜる。同じ動画は**新しいほうを採る**
    # （再生数が伸びているため）。こうしておけば、途中で打ち切られた回があっても
    # 前に取れていた分が消えない。
    merged = dict(kept)
    merged.update({v["id"]: v for v in videos})
    out = list(merged.values())
    added = len(out) - len(kept)
    write_json(DATA / "daily" / f"{today()}.json",
               {"date": today(), "quota_used": yt.used,
                "quota_today": spent + yt.used, "runs": runs + 1,
                "channels_checked": len(targets), "videos": out})
    tall = [v for v in out if (v.get("shape") or 0) > 1.2]
    log(f"保存しました: data/daily/{today()}.json （{len(out)} 本 ／ "
        f"今回取れたのは {len(videos)} 本、新しく増えたのは {added} 本 ／ "
        f"Shorts・切り抜き {skipped} 本を除外）")
    if kept and len(videos) < len(kept) * 0.5:
        log(f"※ 今回取れた本数が、すでにあった {len(kept)} 本よりかなり少なめです。"
            "クォータが足りなかった可能性があります（前の分は残してあります）。")
    if tall:
        log(f"  うち縦長の動画 {len(tall)} 本（いまは数に入れている。様子を見る）")
        for v in sorted(tall, key=lambda x: -x["views"])[:5]:
            log(f"    {v['secs']}秒 比{v['shape']} {v['channel']} — {v['title'][:40]}")
    log(f"本日の使用クォータ: {yt.used}")


if __name__ == "__main__":
    main()
