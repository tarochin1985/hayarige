#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""週・月のまとめ用に「実数」を数える。

    python3 scripts/period_stats.py --month 2026-09
    python3 scripts/period_stats.py --week 2026-10-05        # その日から7日
    python3 scripts/period_stats.py --from 2026-10-01 --to 2026-10-10
    python3 scripts/period_stats.py --month 2026-10 --save   # 台帳に凍結する

なぜ作ったか（2026-10-10 たろちんさん）
--------------------------------------
    > 単発で流行ったゲームが月まとめのランキングに入らないのは
    > 「ハヤリゲー」としては結構もったいない
    > 個人的にはモンストがランキングに入るのも謎だった

9月の月まとめは「のべチャンネル数」（その日のチャンネル数を30日ぶん足した数）
で大きさを測っていた。**これは「何人が遊んだか」ではなく「何人日ぶん
配信されたか」。** 同じ人が毎日出すほど増えるので、

  モンスターストライク    実33人 / 299本 / 1人あたり9.1本
  妹に運転を教える       実110人 / 116本 / 1人あたり1.1本

が、のべだとモンストのほうが上に来る。**110人が触ったゲームが、
33人のゲームに負ける。** 直すのは重みではなく、数える単位のほう。

数えているもの
--------------
  実チャンネル  … その期間に1本以上出した「別々の」チャンネルの数
  本数          … 動画IDで重複を外した本数（48時間ぶん取っているので必要）
  1人あたり     … 本数 ÷ 実チャンネル。**持続力の目印**
  続いた人      … 3本以上出したチャンネルの数と割合
  出た日数      … その期間で1本以上あった日の数
  前半/後半     … 各チャンネルが「その期間で初めて出した日」の分布

30日の壁について
----------------
日別ファイル（data/daily/*.json）は30日で消える。**月の実数は、その月の
ファイルが残っているうちにしか数えられない。** 月まとめは翌月1日に作るので
そのときは全日そろっているが、あとから数え直すことはできない。
だから `--save` で `data/game_periods.json` に凍結する。
範囲が足りないときは、その旨を表示して `full: false` で記録する。
"""
import argparse
import collections
import datetime
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import match as M                                             # noqa: E402
from build_site import choose_name, tag_games                 # noqa: E402
from common import DATA, log, read_json, write_json           # noqa: E402

LEDGER = DATA / "game_periods.json"


def jst_day(s):
    """YouTubeの投稿時刻（UTC）を日本時間の日付にする。"""
    try:
        d = datetime.datetime.strptime(str(s)[:19], "%Y-%m-%dT%H:%M:%S")
    except Exception:
        return ""
    return (d + datetime.timedelta(hours=9)).strftime("%Y-%m-%d")


def daterange(a, b):
    d = datetime.datetime.strptime(a, "%Y-%m-%d")
    e = datetime.datetime.strptime(b, "%Y-%m-%d")
    while d <= e:
        yield d.strftime("%Y-%m-%d")
        d += datetime.timedelta(days=1)


def month_range(ym):
    y, m = (int(x) for x in ym.split("-"))
    a = datetime.date(y, m, 1)
    b = (datetime.date(y + (m == 12), m % 12 + 1, 1)
         - datetime.timedelta(days=1))
    return a.strftime("%Y-%m-%d"), b.strftime("%Y-%m-%d")


def collect(a, b):
    """期間内に投稿された動画を、IDで重複を外して集める。

    日別ファイルは48時間ぶん取っているので、1本の動画が2つのファイルに
    入る。IDで束ねないと本数が倍になる。前日ぶんを拾うため、範囲の
    1日後のファイルまで読む。
    """
    vids, have = {}, []
    last = (datetime.datetime.strptime(b, "%Y-%m-%d")
            + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    for day in daterange(a, last):
        p = DATA / "daily" / f"{day}.json"
        if not p.exists():
            continue
        if day <= b:
            have.append(day)
        for v in (read_json(p, {}) or {}).get("videos") or []:
            d = jst_day(v.get("published"))
            if a <= d <= b:
                v = dict(v)
                v["_day"] = d
                vids[v["id"]] = v
    return list(vids.values()), have


def mid_day(a, b):
    """期間の真ん中の日。前半／後半はこの日を含むまでが前半。"""
    da = datetime.datetime.strptime(a, "%Y-%m-%d")
    db = datetime.datetime.strptime(b, "%Y-%m-%d")
    return (da + (db - da) / 2).strftime("%Y-%m-%d")


def prior_days(a):
    """その日より前に、各ゲームが何日ぶん記録に入っていたか。

    game_days.json は**件数だけの台帳で、消さずに残している**ので、
    日別ファイルが30日で消えたあとも「前からあったゲームか」は分かる。
    """
    gd = read_json(DATA / "game_days.json", {}) or {}
    cnt = collections.Counter()
    for d, games in gd.items():
        if d < a:
            for n in games:
                cnt[n] += 1
    return cnt, (min(gd) if gd else a)


def tally_period(videos, idx, disp, override, a=None, b=None):
    """ゲームごとに実数を数える。build_site の tally と同じ判定を使う。"""
    by_tag, _ = tag_games(videos, idx)
    mid = mid_day(a, b) if a and b else "9999-12-31"
    g = collections.defaultdict(
        lambda: {"n": 0, "ch": collections.Counter(), "days": set(),
                 "first": {}, "titles": [], "views": 0,
                 "h1": set(), "h2": set(),
                 "byday": collections.defaultdict(set)})
    for v in videos:
        name, how = M.extract(v["title"], idx, fallback=True)
        if how != "dict" and v["id"] in by_tag:
            name, how = by_tag[v["id"]], "dict"
        if how != "dict":
            continue
        e = g[name]
        e["n"] += 1
        cid = v.get("channel_id") or v.get("channel") or ""
        e["ch"][cid] += 1
        e["days"].add(v["_day"])
        e["views"] += int(v.get("views") or 0)
        (e["h1"] if v["_day"] <= mid else e["h2"]).add(cid)
        e["byday"][v["_day"]].add(cid)
        if cid not in e["first"] or v["_day"] < e["first"][cid]:
            e["first"][cid] = v["_day"]
        if len(e["titles"]) < 40:
            e["titles"].append(v["title"])
    out = []
    for name, e in g.items():
        uch = len(e["ch"])
        rep = sum(1 for c in e["ch"].values() if c >= 3)
        out.append({
            "game": choose_name(name, disp.get(name), e["titles"], override),
            "key": name, "uch": uch, "n": e["n"], "days": len(e["days"]),
            "rep3": rep, "views": e["views"],
            "per_ch": round(e["n"] / uch, 2) if uch else 0,
            "rep3_pct": round(100 * rep / uch, 1) if uch else 0,
            "first": sorted(e["first"].values()),
            "h1": len(e["h1"]), "h2": len(e["h2"]),
            "byday": {d: len(c) for d, c in e["byday"].items()},
            # 後半が前半の何倍か。前半0人は「0から立ち上がった」ので
            # 割り算にせず、後半の人数をそのまま伸びの大きさとして使う。
            "lift": round(len(e["h2"]) / len(e["h1"]), 2) if e["h1"] else None,
        })
    out.sort(key=lambda x: (-x["uch"], -x["n"]))
    return out


def halves(firsts, a, b):
    """期間を半分に割って、初配信した人の数を前半/後半で出す。"""
    da = datetime.datetime.strptime(a, "%Y-%m-%d")
    db = datetime.datetime.strptime(b, "%Y-%m-%d")
    mid = (da + (db - da) / 2).strftime("%Y-%m-%d")
    first_half = sum(1 for d in firsts if d <= mid)
    return first_half, len(firsts) - first_half


def main():
    ap = argparse.ArgumentParser(description="週・月のまとめ用に実数を数える")
    ap.add_argument("--month", help="YYYY-MM")
    ap.add_argument("--week", help="週の初日 YYYY-MM-DD（7日ぶん）")
    ap.add_argument("--from", dest="a", help="YYYY-MM-DD")
    ap.add_argument("--to", dest="b", help="YYYY-MM-DD")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--rising", action="store_true",
                    help="「期間の急上昇」（後半が前半の何倍か）も出す")
    ap.add_argument("--min-ch", type=int, default=5,
                    help="急上昇に載せる下限（後半の実人数）")
    ap.add_argument("--md", action="store_true",
                    help="noteやまとめに貼れる表の形で出す")
    ap.add_argument("--save", action="store_true",
                    help="data/game_periods.json に凍結する")
    ap.add_argument("--force", action="store_true",
                    help="凍結済みの期間でも上書きする")
    o = ap.parse_args()

    if o.month:
        a, b = month_range(o.month)
        label = o.month
    elif o.week:
        a = o.week
        b = (datetime.datetime.strptime(a, "%Y-%m-%d")
             + datetime.timedelta(days=6)).strftime("%Y-%m-%d")
        label = "w" + a
    elif o.a and o.b:
        a, b = o.a, o.b
        label = f"{a}_{b}"
    else:
        log("--month / --week / --from と --to のどれかを指定してください")
        return 1

    want = list(daterange(a, b))
    videos, have = collect(a, b)
    missing = [d for d in want if d not in have]
    full = not missing
    log(f"期間 {a}〜{b}（{len(want)}日） 元データのある日 {len(have)}日")
    if missing:
        log(f"⚠️ 元データが無い日が {len(missing)}日あります"
            f"（{missing[0]}〜{missing[-1]}）。"
            "日別ファイルは30日で消えるので、この期間の実数はもう揃いません。"
            "ここから下の数字は、残っている日ぶんだけのものです")
    if not videos:
        log("その期間の動画が1本もありませんでした")
        return 1
    log(f"重複を外した動画 {len(videos)}本")

    idx = M.build_index()
    disp = M.load_display()
    override = read_json(DATA / "display_names.json", {}) or {}
    rows = tally_period(videos, idx, disp, override, a, b)
    ch_total = len({v.get("channel_id") or v.get("channel") or ""
                    for v in videos})
    log(f"この期間に1本以上出したチャンネル {ch_total} 件（分母）")

    print()
    print(f"=== {a}〜{b} 実チャンネル数の多い順"
          f"{'' if full else '（元データが足りない期間）'} ===")
    print("%3s %-34s %5s %5s %7s %10s %5s %9s"
          % ("順", "ゲーム", "実人数", "本数", "1人あたり", "3本以上", "日数",
             "初配信 前半/後半"))
    for i, r in enumerate(rows[:o.top], 1):
        fh, sh = halves(r["first"], a, b)
        print("%3d %-34s %5d %5d %7.2f %5d(%4.1f%%) %5d %4d/%-4d"
              % (i, r["game"][:32], r["uch"], r["n"], r["per_ch"],
                 r["rep3"], r["rep3_pct"], r["days"], fh, sh))

    if o.rising:
        mid = mid_day(a, b)
        # 日ごとの分母（その日1本でも出した人の数）。
        # **監視しているチャンネルは増え続けている**ので（8/26は343、10/9は4,098）、
        # 人数をそのまま日どうしで比べると、何もしていないゲームまで伸びて見える。
        # EDITORIAL 7-3章と同じ直し方で、「その日配信した人のうち何%か」に
        # 直してから比べる。
        dtot = collections.Counter()
        for v in videos:
            dtot[v["_day"]] = dtot[v["_day"]]
        seen_day = collections.defaultdict(set)
        for v in videos:
            seen_day[v["_day"]].add(v.get("channel_id") or v.get("channel") or "")
        dtot = {d: len(c) for d, c in seen_day.items()}
        days_all = [d for d in daterange(a, b) if d in dtot]
        # **分母が極端に小さい日は捨てる。** 日別ファイルは48時間ぶん取るので、
        # 残っている最初のファイルの「2日前」が数本だけ入ってくる。
        # その日を同じ物差しで扱うと、11人のゲームが「その日の全体の1割」に
        # なってしまい、ピークを取り違える（2026-10-10に実際にやった。
        # ストリートファイター6のピークが、ふだん27人なのに11人の日と出た）。
        if days_all:
            med_den = statistics.median(dtot[d] for d in days_all)
            thin = [d for d in days_all if dtot[d] < med_den * 0.5]
            if thin:
                log(f"配信者の数が極端に少ない {len(thin)}日は比較から外します"
                    f"（{thin[0]}〜{thin[-1]}）")
            days_all = [d for d in days_all if dtot[d] >= med_den * 0.5]
        base_den = statistics.median(dtot[d] for d in days_all) if days_all else 1

        # 「山の高さ」で並べる。前半／後半で比べる形だと、
        #   月の前半に火が付いて後半に落ちたゲームが落ちる（2026-10-10 たろちんさん）
        # ので、**月のどこで跳ねても拾える形**にした。
        #   ピーク  … その月のいちばん人が多かった日
        #   ふだん  … その月の全日の中央値（出ていない日は0として数える）
        # 差が「その日だけ余計に来た人数」。定番は毎日高いので差が小さく、
        # 跳ねたゲームだけが上に来る。
        out = []
        for r in rows:
            sh = {d: (r["byday"].get(d, 0) / dtot[d]) for d in days_all}
            pk_day = max(sh, key=lambda d: sh[d])
            pk_share = sh[pk_day]
            med_share = statistics.median(sh[d] for d in days_all)
            pk_ch = r["byday"].get(pk_day, 0)
            if pk_ch < o.min_ch:
                continue
            gain = (pk_share - med_share) * base_den
            if gain < 2:
                continue
            out.append(dict(r, pk_day=pk_day, pk_ch=pk_ch,
                            usual=round(med_share * base_den, 1),
                            gain=round(gain, 1),
                            burst=(pk_share / med_share) if med_share else None))
        out.sort(key=lambda r: -r["gain"])

        # ---- 表A「今月の新顔」-------------------------------------------
        # 山の高さだけだと、**1日に集中したもの（発売日・企画）が強く、
        # じわじわ広がったものが弱く出る**（2026-10-10 たろちんさん）。
        # 拾いたいのは後者なので、「前からあったか」で先に分けてしまう。
        #   新顔   … 実人数順。じわじわも発売日ドカンも、どちらもここに入る
        #   既存   … 山の高さ順。マイクラ肝試しのような「跳ねた日」はこちら
        # 1つの点数に混ぜない。混ぜると、どちらの話も読めなくなる。
        pri, ledger_from = prior_days(a)
        NEWCOMER = 3        # 前に2日までしか出ていなければ「新顔」とみなす
        def before_days(r):
            return max(pri.get(r["game"], 0), pri.get(r["key"], 0))
        fresh = [r for r in rows if before_days(r) < NEWCOMER and r["uch"] >= o.min_ch]
        fresh.sort(key=lambda r: -r["uch"])
        print()
        print(f"=== {a}〜{b} 今月の新顔（実人数順）===")
        print(f"台帳 {ledger_from} 以降で、この期間より前に{NEWCOMER}日以上"
              "出ていないゲーム")
        # 「見え始めた日」と「出始めた日」は違う。日別ファイルが残っている
        # いちばん古い日に初登場しているものは、**その前から出ていたのが
        # 見えていないだけ**（辞書に後から足したゲームも同じ顔をする）。
        # 2026-10-10に、モンスターハンターワイルズが新顔として並んだ。
        first_obs = min(dtot) if dtot else a
        print(f"※ 印（!）は、元データのいちばん古い日（{first_obs}）に"
              "初登場しているもの。**その前から出ていたのが見えていないだけ**の"
              "可能性が高いので、落としてください"
              "（辞書に後から足したゲームも同じ顔をします）")
        if o.md:
            print()
            print("| ゲーム | 実人数 | 本数 | 1人あたり | 出た日数 | 初登場 |")
            print("|---|---|---|---|---|---|")
            for r in fresh[:o.top]:
                fd = min(r["byday"]) if r["byday"] else "-"
                mk = " **!**" if fd <= first_obs else ""
                print("| %s%s | **%d人** | %d本 | %.2f本 | %d日 | %s（%d人） |"
                      % (r["game"], mk, r["uch"], r["n"], r["per_ch"],
                         r["days"], fd[5:].replace("-", "/"),
                         r["byday"].get(fd, 0)))
        else:
            print("%3s %-32s %6s %5s %7s %6s %14s"
                  % ("順", "ゲーム", "実人数", "本数", "1人あたり", "日数",
                     "初登場"))
            for i2, r in enumerate(fresh[:o.top], 1):
                fd = min(r["byday"]) if r["byday"] else "-"
                mk = "!" if fd <= first_obs else " "
                print("%s%2d %-32s %5d人 %4d本 %6.2f本 %4d日 %9s(%d人)"
                      % (mk, i2, r["game"][:30], r["uch"], r["n"], r["per_ch"],
                         r["days"], fd[5:].replace("-", "/"),
                         r["byday"].get(fd, 0)))

        # ---- 表B「前からあるゲームが跳ねた日」----------------------------
        out = [r for r in out if before_days(r) >= NEWCOMER]
        print()
        print(f"=== {a}〜{b} 前からあるゲームが跳ねた日（山の高さ順）===")
        print(f"ピーク＝いちばん人が多かった日 ／ ふだん＝{len(days_all)}日の中央値"
              f"（出ていない日は0）。日ごとの分母で補正しています")
        print(f"※ ピークが{o.min_ch}人以上、かつ「ふだん」より2人以上多いものだけ")
        if o.md:
            print()
            print("| ゲーム | ピーク | その日 | ふだん | 増えた人数 | 前半→後半 |")
            print("|---|---|---|---|---|---|")
            for r in out[:o.top]:
                print("| %s | **%d人** | %s | %.1f人 | +%.0f人 | %d→%d人 |"
                      % (r["game"], r["pk_ch"], r["pk_day"][5:].replace("-", "/"),
                         r["usual"], r["gain"], r["h1"], r["h2"]))
        else:
            print("%3s %-32s %6s %7s %7s %8s %11s"
                  % ("順", "ゲーム", "ピーク", "その日", "ふだん", "増えた",
                     "前半→後半"))
            for i2, r in enumerate(out[:o.top], 1):
                print("%3d %-32s %5d人 %7s %6.1f人 %+7.0f %5d→%-5d"
                      % (i2, r["game"][:30], r["pk_ch"],
                         r["pk_day"][5:].replace("-", "/"), r["usual"],
                         r["gain"], r["h1"], r["h2"]))

    if o.save:
        led = read_json(LEDGER, {}) or {}
        if label in led and led[label].get("full") and not o.force:
            log(f"{label} はすでに全日そろった形で凍結されています。"
                "上書きするなら --force")
        else:
            led[label] = {
                "from": a, "to": b, "full": full,
                "days_have": len(have), "days_want": len(want),
                "counted": datetime.date.today().strftime("%Y-%m-%d"),
                # 台帳に残すのは数だけ。題やチャンネルIDは持たない
                # 月をまたいで比べるときの分母（EDITORIAL 7-3章）。
                # 監視チャンネルが増え続けているので、人数をそのまま
                # 引き算・割り算すると何もしていないゲームまで伸びて見える。
                "channels_total": ch_total,
                # [実人数, 本数, 日数, 3本以上, 前半の人数, 後半の人数]
                "games": {r["key"]: [r["uch"], r["n"], r["days"], r["rep3"],
                                     r["h1"], r["h2"]]
                          for r in rows},
            }
            write_json(LEDGER, dict(sorted(led.items())))
            log(f"{LEDGER.name} に {label} を書きました"
                f"（{len(rows)}ゲーム / full={full}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
