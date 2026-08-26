#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""集計してサイトを書き出す。fetch_daily.py のあとに動かす。

出力: site/index.html と site/data.json
"""
import math, re
from collections import defaultdict
from datetime import datetime, timedelta
from urllib.parse import quote
from common import DATA, SITE, JST, log, read_json, write_json, today
import match as M

DAYS = 7
MIN_FOR_MOMENTUM = 3          # 急上昇の対象にする最低本数（少数のブレを弾く）
W = {"videos": 0.30, "channels": 0.35, "views": 0.35}


def load_days(n=DAYS):
    out = []
    for d in range(n - 1, -1, -1):
        day = (datetime.now(JST) - timedelta(days=d)).strftime("%Y-%m-%d")
        out.append((day, (read_json(DATA / "daily" / f"{day}.json", {}) or {}).get("videos", [])))
    return out


def series_sig(title: str) -> str:
    """連番シリーズをまとめるための署名。1人の連投で順位が動かないようにする。"""
    return M.compact(re.sub(r"[0-9#＃]+", "", title))[:16]


def tally(videos, idx):
    games = defaultdict(lambda: {"videos": 0, "sigs": set(), "channels": set(),
                                 "views": 0, "streams": [], "orgs": defaultdict(int)})
    unknown = []
    for v in videos:
        g, how = M.extract(v["title"], idx, fallback=True)
        if how == "dict":
            e = games[g]
            e["videos"] += 1
            e["sigs"].add(series_sig(v["title"]))
            e["channels"].add(v["channel_id"])
            e["views"] += v.get("views", 0)
            e["orgs"][v.get("affiliation") or "個人・その他"] += 1
            if len(e["streams"]) < 12:
                e["streams"].append({"t": v["title"], "c": v["channel"],
                                     "u": f"https://www.youtube.com/watch?v={v['id']}",
                                     "th": v.get("thumb", ""), "v": v.get("views", 0)})
        elif how == "unknown":
            unknown.append({"title": v["title"], "guess": g, "channel": v["channel"],
                            "u": f"https://www.youtube.com/watch?v={v['id']}"})
    return games, unknown


def main():
    idx = M.build_index()
    days = load_days()
    day_names = [d for d, _ in days]
    today_videos = days[-1][1]
    log(f"直近{DAYS}日: " + " ".join(f"{d[5:]}={len(v)}" for d, v in days))

    # 日ごとのゲーム別本数（推移と急上昇に使う）
    hist = {}
    for day, vids in days:
        g, _ = tally(vids, idx)
        hist[day] = {k: len(v["sigs"]) for k, v in g.items()}

    games, unknown = tally(today_videos, idx)
    if not games:
        log("今日のデータからゲームを検出できませんでした。処理を続けます。")

    rows = []
    for name, e in games.items():
        rows.append({"game": name, "videos": len(e["sigs"]), "raw": e["videos"],
                     "channels": len(e["channels"]), "views": e["views"],
                     "streams": sorted(e["streams"], key=lambda s: -s["v"])[:8],
                     "orgs": dict(sorted(e["orgs"].items(), key=lambda x: -x[1])),
                     "spark": [hist.get(d, {}).get(name, 0) for d in day_names]})
    if rows:
        mx_v = max(r["videos"] for r in rows) or 1
        mx_c = max(r["channels"] for r in rows) or 1
        logs_ = [math.log10(1 + r["views"]) for r in rows]
        lo, hi = min(logs_), max(logs_)
        for r in rows:
            r["p_videos"] = round(r["videos"] / mx_v * 100)
            r["p_channels"] = round(r["channels"] / mx_c * 100)
            r["p_views"] = round((math.log10(1 + r["views"]) - lo) / max(1e-9, hi - lo) * 100)
            r["score"] = round(r["p_videos"] * W["videos"] + r["p_channels"] * W["channels"]
                               + r["p_views"] * W["views"], 1)
            early = sum(r["spark"][:3]) / 3
            r["growth"] = round(r["videos"] / max(0.8, early), 2)
            r["steam"] = "https://store.steampowered.com/search/?term=" + quote(r["game"])
            r["amazon"] = "https://www.amazon.co.jp/s?k=" + quote(r["game"])
        rows.sort(key=lambda r: -r["score"])
        for i, r in enumerate(rows, 1):
            r["rank"] = i

    rising = sorted([r for r in rows if r["videos"] >= MIN_FOR_MOMENTUM and r["growth"] > 1.25],
                    key=lambda r: -r["growth"])[:3]

    payload = {
        "date": today(),
        "generated": datetime.now(JST).strftime("%Y-%m-%d %H:%M"),
        "days": [d[5:].replace("-", "/") for d in day_names],
        "totals": {"videos": len(today_videos), "games": len(rows),
                   "channels": len({v["channel_id"] for v in today_videos})},
        "rising": rising,
        "ranking": rows[:30],
        "unknown": unknown[:20],
    }
    write_json(SITE / "data.json", payload)

    tpl = (SITE / "template.html").read_text(encoding="utf-8")
    import json
    (SITE / "index.html").write_text(
        tpl.replace("__DATA__", json.dumps(payload, ensure_ascii=False)), encoding="utf-8")
    log(f"サイトを書き出しました: {len(rows)} タイトル / 急上昇 {len(rising)} 件 "
        f"/ 確認待ち {len(unknown)} 件")


if __name__ == "__main__":
    main()
