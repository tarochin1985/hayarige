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
MIN_HISTORY = 4               # 急上昇を出すのに必要な「実データのある日数」
W = {"videos": 0.30, "channels": 0.35, "views": 0.35}


def load_days(n=DAYS):
    """(日付, 動画リスト, その日のデータがあるか) を古い順に返す。

    集計を始めたばかりの頃は過去のファイルが存在しない。それを「0本の日」と
    数えてしまうと、どのゲームも『昨日の30倍！』という嘘の急上昇になる。
    データが無い日は無い日として区別する。
    """
    out = []
    for d in range(n - 1, -1, -1):
        day = (datetime.now(JST) - timedelta(days=d)).strftime("%Y-%m-%d")
        rec = read_json(DATA / "daily" / f"{day}.json", None)
        out.append((day, (rec or {}).get("videos", []), rec is not None))
    return out


def series_sig(title: str) -> str:
    """連番シリーズをまとめるための署名。1人の連投で順位が動かないようにする。"""
    return M.compact(re.sub(r"[0-9#＃]+", "", title))[:16]


def tally(videos, idx):
    games = defaultdict(lambda: {"videos": 0, "sigs": set(), "channels": set(),
                                 "views": 0, "streams": [], "titles": [],
                                 "orgs": defaultdict(int)})
    unknown = []
    for v in videos:
        g, how = M.extract(v["title"], idx, fallback=True)
        if how == "dict":
            e = games[g]
            e["videos"] += 1
            e["sigs"].add(series_sig(v["title"]))
            e["channels"].add(v["channel_id"])
            e["views"] += v.get("views", 0)
            e["titles"].append(v["title"])
            e["orgs"][v.get("affiliation") or "個人・その他"] += 1
            if len(e["streams"]) < 12:
                e["streams"].append({"t": v["title"], "c": v["channel"],
                                     "u": f"https://www.youtube.com/watch?v={v['id']}",
                                     "th": v.get("thumb", ""), "v": v.get("views", 0)})
        elif how == "unknown":
            unknown.append({"title": v["title"], "guess": g, "channel": v["channel"],
                            "u": f"https://www.youtube.com/watch?v={v['id']}"})
    return games, unknown


def choose_name(canonical, jp, titles, override):
    """英語名と日本語名のどちらで表示するかを、実際の配信タイトルから決める。
    配信者が『APEX』と書くならAPEX、『日本事故物件監視協会』と書くならそちら。"""
    if canonical in override:
        return override[canonical]
    if not jp or jp == canonical:
        return canonical
    blob = " ".join(M.compact(t) for t in titles)
    return jp if blob.count(M.compact(jp)) >= blob.count(M.compact(canonical)) else canonical


def main():
    idx = M.build_index()
    disp = M.load_display()
    override = read_json(DATA / "display_names.json", {}) or {}
    days = load_days()
    day_names = [d for d, _, _ in days]
    have = [d for d, _, ok in days if ok]
    today_videos = days[-1][1]
    log(f"直近{DAYS}日: " + " ".join(f"{d[5:]}={len(v) if ok else '-'}"
                                    for d, v, ok in days))
    log(f"実データのある日数: {len(have)} / 急上昇の表示には {MIN_HISTORY} 日必要")

    # 日ごとのゲーム別本数（推移と急上昇に使う）
    hist = {}
    for day, vids, ok in days:
        if not ok:
            continue
        g, _ = tally(vids, idx)
        hist[day] = {k: len(v["sigs"]) for k, v in g.items()}
    momentum_ready = len(have) >= MIN_HISTORY

    games, unknown = tally(today_videos, idx)
    if not games:
        log("今日のデータからゲームを検出できませんでした。処理を続けます。")

    rows = []
    for name, e in games.items():
        rows.append({"game": choose_name(name, disp.get(name), e["titles"], override),
                     "canonical": name, "videos": len(e["sigs"]), "raw": e["videos"],
                     "channels": len(e["channels"]), "views": e["views"],
                     "streams": sorted(e["streams"], key=lambda s: -s["v"])[:8],
                     "orgs": dict(sorted(e["orgs"].items(), key=lambda x: -x[1])),
                     "spark": [hist[d].get(name, 0) if d in hist else None
                               for d in day_names]})
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
            # 急上昇は「実データのある過去の日」とだけ比べる
            past = [v for d, v in zip(day_names, r["spark"])
                    if d in hist and d != day_names[-1] and v is not None]
            if momentum_ready and past:
                r["growth"] = round(r["videos"] / max(0.8, sum(past) / len(past)), 2)
            else:
                r["growth"] = None
            r["steam"] = "https://store.steampowered.com/search/?term=" + quote(r["game"])
            r["amazon"] = "https://www.amazon.co.jp/s?k=" + quote(r["game"])
        rows.sort(key=lambda r: -r["score"])
        for i, r in enumerate(rows, 1):
            r["rank"] = i

    rising = sorted([r for r in rows if r["videos"] >= MIN_FOR_MOMENTUM
                     and (r["growth"] or 0) > 1.25],
                    key=lambda r: -r["growth"])[:3] if momentum_ready else []
    # 急上昇が出せない間は「今日いちばん多くの配信者が触ったゲーム」を代わりに出す
    spread = sorted(rows, key=lambda r: (-r["channels"], -r["videos"]))[:3]

    payload = {
        "date": today(),
        "generated": datetime.now(JST).strftime("%Y-%m-%d %H:%M"),
        "days": [d[5:].replace("-", "/") for d in day_names],
        "totals": {"videos": len(today_videos), "games": len(rows),
                   "channels": len({v["channel_id"] for v in today_videos})},
        "rising": rising,
        "spread": spread,
        "momentum": {"ready": momentum_ready, "days": len(have), "need": MIN_HISTORY},
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
