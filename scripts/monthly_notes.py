#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""note用の「裏話レポート」を作る。月まとめを書くときに1回だけ走らせる。

    python scripts/monthly_notes.py 2026-09

サイトに載せる月まとめは「裏が取れた事実」だけで書く。こちらはその逆で、
サイトには書けないもの——運営の失敗、辞書を直した話、数字の裏で何が
起きていたか——を集めて、note用の下書きの材料にする。
（2026-09-20 たろちんさんと決めた）

出すもの:
  note_YYYY-MM.html … グラフと表の入ったレポート。そのまま読める1枚
  標準出力          … 同じ内容の要約。noteの本文を書くときの材料

集めるもの:
  1. 運営の裏側      … その月に辞書へ足したもの・直したもの（gitの履歴から）
  2. ランキングの動き … 初登場・その月のピーク・1日でいちばん伸びた日
  3. 急上昇に出たもの … 記録ページの数字から当時の倍率を計算し直す
  4. PVの推移        … data/pv.csv があれば（無ければその旨を出す）
"""
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE_D = ROOT / "site" / "d"
DATA = ROOT / "data"

# 判定に効くファイル。ここの変更が「辞書を直した」履歴になる。
WATCH = ["data/aliases.json", "data/display_names.json", "data/blocklist.json",
         "data/alias_blocklist.json", "data/game_blocklist.json",
         "data/platforms.json", "data/channels_manual.json"]

# 折れ線の色。dataviz の既定パレットの1〜4番目。
# 明るい側は緑と黄が背景とのコントラストで下限に届かないので、
# 線の右端に必ず名前を出し、下に表も付ける（それが条件になっている）。
SERIES_L = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
SERIES_D = ["#3987e5", "#d95926", "#199e70", "#c98500"]


def log(*a):
    print(*a, file=sys.stderr)


def read_day(day):
    """記録ページから、その日のランキングを取り出す。"""
    f = SITE_D / day / "index.html"
    if not f.is_file():
        return None
    try:
        h = f.read_text(encoding="utf-8")
        i = h.index("const DATA = ") + len("const DATA = ")
        obj, _ = json.JSONDecoder().raw_decode(h[i:])
        return obj
    except (ValueError, OSError):
        return None


def load_month(month):
    out = {}
    for d in sorted(SITE_D.iterdir()) if SITE_D.is_dir() else []:
        if d.is_dir() and d.name.startswith(month):
            o = read_day(d.name)
            if o:
                out[d.name] = o
    return out


def all_days():
    if not SITE_D.is_dir():
        return []
    return sorted(d.name for d in SITE_D.iterdir()
                  if d.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d.name))


# ---------------------------------------------------------------- 1. 運営の裏側
def git(*args):
    try:
        r = subprocess.run(["git", "-C", str(ROOT)] + list(args),
                           capture_output=True, text=True, timeout=60)
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def unshallow():
    """浅いクローンだと履歴が読めない。読めるようにしておく。"""
    if (ROOT / ".git" / "shallow").exists():
        log("履歴が浅いので取り直しています…")
        git("fetch", "--unshallow", "--quiet")


def dict_changes(month):
    """その月に辞書へ足されたもの・消されたものを、gitの履歴から拾う。

    JSONの差分をそのまま出しても読めないので、足された行だけを拾って
    「何というゲームを足したか」の一覧にする。
    """
    unshallow()
    since, until = month + "-01", month + "-32"
    label = {"data/aliases.json": "ゲームを足した",
             "data/display_names.json": "表示名を直した",
             "data/blocklist.json": "ゲーム名でない言葉を除外した",
             "data/alias_blocklist.json": "紛らわしい別名を除外した",
             "data/game_blocklist.json": "ゲームごと除外した",
             "data/platforms.json": "売っている場所を直した",
             "data/channels_manual.json": "チャンネルを手で外した"}
    out = []
    logtxt = git("log", "--format=%H\t%ad", "--date=short",
                 f"--since={since}", f"--until={until}", "--", *WATCH)
    for line in logtxt.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        sha, date = parts[0], parts[1]
        groups = {}
        for path in WATCH:
            diff = git("show", "--format=", "--unified=0", sha, "--", path)
            added, removed = [], []
            for ln in diff.splitlines():
                if ln.startswith("+++") or ln.startswith("---"):
                    continue
                m = re.match(r'^([+-])\s*"([^"]{1,60})"\s*:', ln)
                if m and not m.group(2).startswith("_"):    # 辞書のキー＝1本
                    (added if m.group(1) == "+" else removed).append(m.group(2))
                    continue
                m2 = re.match(r'^([+-])\s*"([^"]{1,40})",?\s*$', ln)   # 単純な一覧
                if m2:
                    (added if m2.group(1) == "+" else removed).append(m2.group(2))
            # JSONを書き出し直すと、動いていない項目まで差分に出る。
            # ＋と−の両方にある名前は「中身を書き換えただけ」なので落とす。
            both = set(added) & set(removed)
            added = [x for x in dict.fromkeys(added) if x not in both]
            removed = [x for x in dict.fromkeys(removed) if x not in both]
            if added or removed:
                groups[label.get(path, path)] = {"added": added[:30],
                                                 "removed": removed[:15]}
        if groups:
            out.append({"date": date, "groups": groups})
    out.sort(key=lambda x: x["date"])
    return out


# ------------------------------------------------------------ 2. ランキングの動き
def movements(month, days):
    """その月のランキングで目についた動きを拾う。"""
    before = [d for d in all_days() if d < month + "-01"]
    seen_before = set()
    for d in before:
        o = read_day(d)
        if o:
            seen_before |= {r["game"] for r in o.get("ranking", [])}

    peak, first, byday = {}, {}, sorted(days)
    for d in byday:
        for r in days[d].get("ranking", []):
            g = r["game"]
            first.setdefault(g, d)
            if r["channels"] > peak.get(g, (0, ""))[0]:
                peak[g] = (r["channels"], d)

    debut = [{"game": g, "day": first[g], "peak": peak[g][0], "peak_day": peak[g][1]}
             for g in first if g not in seen_before]
    debut.sort(key=lambda x: -x["peak"])

    # 前の日とくらべて、配信者数がいちばん増えた日
    jumps = []
    for a, b in zip(byday, byday[1:]):
        pa = {r["game"]: r["channels"] for r in days[a].get("ranking", [])}
        for r in days[b].get("ranking", []):
            d = r["channels"] - pa.get(r["game"], 0)
            if d >= 5:
                was = pa.get(r["game"], 0)
                jumps.append({"game": r["game"], "day": b,
                              "from": f"{was}ch" if was else "圏外",
                              "to": r["channels"], "diff": d})
    jumps.sort(key=lambda x: -x["diff"])

    top = sorted(peak.items(), key=lambda kv: -kv[1][0])[:5]
    return {"debut": debut[:12], "jumps": jumps[:12],
            "top": [{"game": g, "peak": v[0], "day": v[1]} for g, v in top]}


def rising_again(month, days):
    """当時の急上昇欄を、記録ページの数字から計算し直す。

    記録ページには急上昇そのものが残っていない（作り直すときに空になる）。
    ただし日ごとの配信者数と件数は全期間残っているので、同じ計算で再現できる。
    """
    byday = sorted(all_days())
    cnt = {}
    for d in byday:
        o = read_day(d)
        cnt[d] = {r["game"]: r["videos"] for r in (o or {}).get("ranking", [])}
    ch = {}
    for d in byday:
        o = read_day(d)
        ch[d] = {r["game"]: r["channels"] for r in (o or {}).get("ranking", [])}

    out = []
    for i, d in enumerate(byday):
        if not d.startswith(month) or i < 4:
            continue
        past = byday[max(0, i - 6):i]
        rows = []
        for g, n in cnt[d].items():
            if n < 3 or ch[d].get(g, 0) < 3:
                continue
            base = sum(cnt[p].get(g, 0) for p in past) / max(len(past), 1)
            gr = n / max(0.8, base)
            if gr > 1.25:
                rows.append((round(gr, 1), g, n, ch[d][g]))
        rows.sort(reverse=True)
        for gr, g, n, c in rows[:6]:
            out.append({"day": d, "game": g, "growth": gr, "videos": n, "channels": c})
    tally = defaultdict(list)
    for r in out:
        tally[r["game"]].append(r)
    ranked = sorted(tally.items(), key=lambda kv: (-len(kv[1]),
                                                   -max(x["growth"] for x in kv[1])))
    return [{"game": g, "days": len(v),
             "best": max(v, key=lambda x: x["growth"])} for g, v in ranked[:12]]


# ------------------------------------------------- サイトの月まとめ用の材料
# ここから下は note の裏話ではなく、**サイトに載せる月まとめ**を書くための材料。
# （2026-09-21 たろちんさんと決めた）
#
# 月まとめの主役は「今月伸びたゲーム3本」。総数の多い順ではない。
# 総数で並べると毎月おなじ顔ぶれになることを、26日ぶんのデータで確かめた。
# 窓を3つに切って上位5を出したら、どの2つを比べても重なりが4/5あり、
# 上位3本は3つの窓すべてで Minecraft・Apex・ストリートファイター6 だった。
# 順番が入れ替わるだけで、顔ぶれは動かない。それでは「流行った」の記事にならない。
#
# ■ 人数をそのまま比べてはいけない（2026-09-21に気づいて直した）
#
# このサイトが見ているチャンネルは増え続けている。8月26日は343、9月20日は1,977。
# 実際に配信していた人の数も 392人 → 807人 と倍以上になった。
# だから「配信した人数」をそのまま月どうしで比べると、**何もしていないゲームまで
# 増えたように見える。** 実際、生の人数で並べると Apex が9月の伸びた順の4位に
# 来るが、割合で見ると順位表から消える。増えたのは Apex ではなく、こちらの目の数。
#
# なので、その日「配信していた人のうち何%がそのゲームを配信したか」で比べる。
# 分母（totals.channels）は記録ページに永久に残るので、何年でも比べられる。

def day_rows(day):
    """その日のランキングを {ゲーム名: (人数, 割合%)} で返す。

    割合は「その日配信していた人のうち何%か」。見ているチャンネルが
    増えても意味が変わらないので、月どうしを比べるときはこちらを使う。
    """
    o = read_day(day) or {}
    tot = (o.get("totals") or {}).get("channels") or 0
    if not tot:
        return {}
    return {r["game"]: (r.get("channels", 0), r.get("channels", 0) / tot * 100)
            for r in o.get("ranking", [])}


def window(ds):
    """日付の一覧から、ゲームごとの1日あたり平均（人数と割合）を出す。

    記録ページに残っているのは各日の上位30件まで。30位に入らなかった日は
    0として平均するので、小さいゲームの数字はやや低めに出る。
    伸びたものを見つける用途なら、これで足りる。
    """
    ch, sh = defaultdict(float), defaultdict(float)
    for d in ds:
        for g, (c, s) in day_rows(d).items():
            ch[g] += c
            sh[g] += s
    n = max(len(ds), 1)
    return {g: {"ch": ch[g] / n, "sh": sh[g] / n} for g in ch}


def month_days(month):
    return [d for d in all_days() if d.startswith(month)]


def prev_month(month):
    y, m = int(month[:4]), int(month[5:7])
    return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"


def peak_of(game, ds):
    """そのゲームがいちばん多く配信された日と、その日の代表的な配信3本。"""
    best = (0, "", [])
    for d in ds:
        for r in (read_day(d) or {}).get("ranking", []):
            if r["game"] == game and r.get("channels", 0) > best[0]:
                st = sorted(r.get("streams") or [], key=lambda s: -s.get("v", 0))
                best = (r["channels"], d, st[:3])
    return {"channels": best[0], "day": best[1], "streams": best[2]}


def grew(month):
    """今月いちばん伸びたゲームを出す。月まとめの1〜3位の候補になる。

    比べる相手は先月。先月の記録が5日に満たないとき（サイトを始めた最初の月など）
    は、同じ月の前半と後半を比べる。どちらで比べたかは呼び出し側に返す。
    """
    cur_days = month_days(month)
    if not cur_days:
        return None
    prev_days = month_days(prev_month(month))
    cur = window(cur_days)
    if len(prev_days) >= 5:
        basis = f"先月（{prev_month(month)}／{len(prev_days)}日）とくらべて"
        base, target, tgt_days = window(prev_days), cur, cur_days
    else:
        half = len(cur_days) // 2
        if half < 3:
            return None
        early, late = cur_days[:half], cur_days[half:]
        basis = (f"この月の前半（{early[0][5:]}〜{early[-1][5:]}）と"
                 f"後半（{late[0][5:]}〜{late[-1][5:]}）をくらべて")
        base, target, tgt_days = window(early), window(late), late

    seen_before = set()
    for d in all_days():
        if d >= month + "-01":
            break
        seen_before |= set(day_rows(d))

    rows = []
    for g, a in target.items():
        if a["sh"] < 0.5 or a["ch"] < 3:     # 小さすぎるものは拾わない
            continue
        b = base.get(g) or {"ch": 0.0, "sh": 0.0}
        rows.append({"game": g, "new": g not in seen_before,
                     "before_ch": round(b["ch"], 1), "after_ch": round(a["ch"], 1),
                     "before": round(b["sh"], 2), "after": round(a["sh"], 2),
                     "diff": round(a["sh"] - b["sh"], 2)})
    rows.sort(key=lambda x: -x["diff"])
    rows = rows[:10]
    for r in rows:
        r["peak"] = peak_of(r["game"], tgt_days)

    # 定番（割合の大きい順）。先月と顔ぶれが変わったかどうかを見るために出す。
    prev = window(prev_days) if prev_days else {}
    top = sorted(cur.items(), key=lambda kv: -kv[1]["sh"])[:5]
    ptop = [g for g, _ in sorted(prev.items(), key=lambda kv: -kv[1]["sh"])[:3]]
    ctop = [g for g, _ in top[:3]]
    if len(prev_days) < 5:
        shift = "先月の記録が足りないので、くらべられません。"
    elif set(ctop) == set(ptop):
        shift = ("先月のトップ3と同じ顔ぶれです（順番だけ違うことがあります）。"
                 "同じ状態が続くなら、月まとめで触れなくて構いません。")
    else:
        gone = [g for g in ptop if g not in ctop]
        came = [g for g in ctop if g not in ptop]
        shift = ("★ 先月から入れ替わりました。"
                 + ("落ちた: " + "、".join(gone) + "　" if gone else "")
                 + ("入った: " + "、".join(came) if came else "")
                 + " ── 入れ替わり自体がひとつのトピックになります。")
    return {"basis": basis, "rows": rows, "days": len(cur_days), "shift": shift,
            "staples": [{"game": g, "sh": round(v["sh"], 2), "ch": round(v["ch"], 1),
                         "diff": (round(v["sh"] - prev[g]["sh"], 2)
                                  if g in prev else None)} for g, v in top]}


def column_brief(month, gr):
    """サイトの月まとめを書く人へ渡す、文字だけの材料。"""
    if not gr:
        return (f"■ {month} サイトの月まとめ用の材料\n"
                "　記録ページが足りないため、伸びたゲームを出せませんでした。")
    o = [f"■ {month} サイトの月まとめ用の材料（記録 {gr['days']}日）",
         f"　並べ方: {gr['basis']}、『その日配信していた人のうち何%がそのゲームを",
         "　　　　　配信したか』がどれだけ増えたか。",
         "　　　　　人数をそのまま比べない。見ているチャンネルが増え続けているので、",
         "　　　　　人数だと何もしていないゲームまで増えたように見えるため。",
         "",
         "【今月伸びたゲーム ── 1〜3位の候補】"]
    for i, r in enumerate(gr["rows"], 1):
        mark = "（今月が初登場）" if r["new"] else ""
        o.append(f"{i:2d}. {r['game']}{mark}")
        o.append(f"      配信していた人の {r['before']}% → {r['after']}%"
                 f"（+{r['diff']}ポイント）")
        o.append(f"      1日あたりの人数では {r['before_ch']}人 → {r['after_ch']}人")
        p = r["peak"]
        if p["day"]:
            o.append(f"      いちばん多かった日: {p['day']}（{p['channels']}人）")
        for s in p["streams"]:
            o.append(f"        ・{s.get('c', '')} — {s.get('t', '')[:52]}"
                     f"（{s.get('v', 0):,}回）")
    o += ["", "【定番（割合の大きい順）】"]
    for s in gr["staples"]:
        d = "" if s["diff"] is None else f"（先月比 {s['diff']:+.2f}ポイント）"
        o.append(f"　{s['game']}　{s['sh']}%（1日あたり {s['ch']}人）{d}")
    o += ["", "　" + gr["shift"], "",
          "【この材料の使い方】",
          "　・1〜3位は、上の候補から『なぜ増えたかを説明できるもの』を選ぶ。",
          "　　数字の大きい順に機械的に選ばない。理由が書けないものは落とす。",
          "　・理由は一次ソースで裏を取る（発売日、公式の告知、企画のページ）。",
          "　・代表的な配信は、その日の再生数の多い順に出してある。",
          "　　本文に入れるなら、実際に開いて中身を確かめてから。",
          "　・本文に書く数字は『人数』のほうがよい。割合は並べ替えのための物差しで、",
          "　　読者には『18人が配信した』のほうが伝わる。",
          "　・『定番』は、先月と顔ぶれが同じなら書かなくてよい。",
          "　　入れ替わったときだけ、それ自体をひとつの節にする。",
          "　・記録ページは上位30件までなので、30位に入らなかった日は0として",
          "　　平均している。小さいゲームの数字は実際よりやや低く出る。"]
    return "\n".join(o)


def hand_notes(month):
    """data/columns/運営メモ.md から、その月のぶんを取り出す。

    gitの履歴には「何を直したか」は残るが「なぜそうなっていたか」は残らない。
    そこがいちばん読み物になるので、直したときに手で書き足している。
    見出しが「## YYYY-MM-DD 〜」の形になっている前提。
    """
    f = DATA / "columns" / "運営メモ.md"
    if not f.is_file():
        return []
    out, cur = [], None
    for ln in f.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^##\s+(\d{4}-\d{2}-\d{2})\s+(.+?)\s*$", ln)
        if m:
            cur = {"date": m.group(1), "title": m.group(2), "body": []}
            out.append(cur)
        elif cur is not None and ln.strip():
            cur["body"].append(ln.rstrip())
    return [x for x in out if x["date"].startswith(month)]


# ------------------------------------------------------------------- 3. PV
def load_pv(month):
    """data/pv.csv を読む。1行1日で「日付,PV」。手で貼れる形にしてある。"""
    f = DATA / "pv.csv"
    if not f.is_file():
        return []
    out = []
    for ln in f.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*(\d{4}-\d{2}-\d{2})\s*,\s*([0-9,]+)", ln)
        if m and m.group(1).startswith(month):
            out.append((m.group(1), int(m.group(2).replace(",", ""))))
    return sorted(out)


# ------------------------------------------------------------------ グラフ
def e(x):
    return (str(x).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def md(x):
    """運営メモで使う最小限の記法だけHTMLにする。**太字** と `コード`。"""
    t = e(x)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    return t


def line_chart(labels, series, unit="", height=250):
    """折れ線。線は2px、点は8px、右端に名前を出す。下に表も付ける。

    色だけで見分けさせない（名前を必ず添える）。淡い色が背景に近いので、
    そこは表と直接ラベルで補う。
    """
    if not labels or not series:
        return '<p class="none">データがありません。</p>'
    W, H = 760, height
    L, R, T, B = 44, 128, 16, 30
    hi = max((max(v for v in s["values"] if v is not None) for s in series
              if any(v is not None for v in s["values"])), default=1) or 1
    hi = hi * 1.12
    n = max(len(labels) - 1, 1)
    x = lambda i: L + (W - L - R) * i / n
    y = lambda v: T + (H - T - B) * (1 - v / hi)

    g = [f'<svg viewBox="0 0 {W} {H}" role="img" class="chart">']
    for k in range(5):                                   # 目盛り（控えめに）
        v = hi * k / 4
        yy = y(v)
        g.append(f'<line x1="{L}" x2="{W-R}" y1="{yy:.1f}" y2="{yy:.1f}" class="grid"/>')
        g.append(f'<text x="{L-8}" y="{yy+4:.1f}" class="ax" text-anchor="end">'
                 f'{int(v):,}</text>')
    step = max(1, len(labels) // 8)
    last = len(labels) - 1
    show = [i for i in range(len(labels)) if i % step == 0]
    if show and last - show[-1] < step * 0.7:   # 右端と近すぎるものは消す
        show.pop()
    show.append(last)
    for i, lb in enumerate(labels):
        if i in show:
            g.append(f'<text x="{x(i):.1f}" y="{H-8}" class="ax" '
                     f'text-anchor="middle">{e(lb[5:])}</text>')
    for si, s in enumerate(series):
        pts = [(x(i), y(v)) for i, v in enumerate(s["values"]) if v is not None]
        if not pts:
            continue
        d = "M" + " L".join(f"{px:.1f},{py:.1f}" for px, py in pts)
        c = f"var(--s{si+1})"
        g.append(f'<path d="{d}" fill="none" stroke="{c}" stroke-width="2" '
                 f'stroke-linejoin="round" stroke-linecap="round"/>')
        for i, v in enumerate(s["values"]):
            if v is None:
                continue
            g.append(f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="4" fill="{c}" '
                     f'stroke="var(--surface)" stroke-width="2">'
                     f'<title>{e(s["name"])} ／ {e(labels[i])} ／ {v:,}{e(unit)}</title>'
                     f'</circle>')
        lx, ly = pts[-1]
        g.append(f'<text x="{lx+9:.1f}" y="{ly+4:.1f}" class="lbl" fill="{c}">'
                 f'{e(s["name"][:11])}</text>')
    g.append("</svg>")

    th = "".join(f"<th>{e(l[5:])}</th>" for l in labels)
    tb = ""
    for si, s in enumerate(series):
        tds = "".join(f"<td>{'' if v is None else format(v, ',')}</td>"
                      for v in s["values"])
        tb += (f'<tr><th scope="row"><span class="dot" '
               f'style="background:var(--s{si+1})"></span>{e(s["name"])}</th>{tds}</tr>')
    table = (f'<details class="tbl"><summary>数字で見る</summary><div class="scroll">'
             f'<table><thead><tr><th></th>{th}</tr></thead><tbody>{tb}</tbody>'
             f'</table></div></details>')
    return "".join(g) + table


# ------------------------------------------------------------------ 組み立て
CSS = """
:root{color-scheme:light;
 --surface:#fff;--ground:#F3F5F4;--line:#DBE4E2;--ink:#111B1D;--ink-2:#3E5457;--ink-3:#6F8688;
 --accent:#0B6B70;--hot:#B4551C;
 --s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--s4:#eda100}
@media(prefers-color-scheme:dark){:root:where(:not([data-theme="light"])){color-scheme:dark;
 --surface:#141E1F;--ground:#0D1415;--line:#27383A;--ink:#E8EFEE;--ink-2:#A2B7B8;--ink-3:#7C9294;
 --accent:#48BEC2;--hot:#E8975C;
 --s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500}}
:root[data-theme="dark"]{color-scheme:dark;
 --surface:#141E1F;--ground:#0D1415;--line:#27383A;--ink:#E8EFEE;--ink-2:#A2B7B8;--ink-3:#7C9294;
 --accent:#48BEC2;--hot:#E8975C;
 --s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500}
*{box-sizing:border-box}
body{margin:0;padding:26px 16px 70px;background:var(--ground);color:var(--ink);
 font-family:"Hiragino Kaku Gothic ProN","Yu Gothic",system-ui,sans-serif;line-height:1.75}
.wrap{max-width:880px;margin:0 auto}
h1{font-size:23px;margin:0 0 4px}
.sub{color:var(--ink-3);font-size:13px;margin:0 0 22px}
section{background:var(--surface);border:1px solid var(--line);border-radius:13px;
 padding:19px 21px;margin-bottom:15px}
h2{font-size:17px;margin:0 0 4px;display:flex;align-items:center;gap:8px}
h2 .n{font-size:11px;font-weight:700;color:var(--surface);background:var(--accent);
 border-radius:20px;padding:2px 9px}
.note{color:var(--ink-3);font-size:12.5px;margin:0 0 14px}
.chart{width:100%;height:auto;display:block;margin:6px 0 2px}
.grid{stroke:var(--line);stroke-width:1}
.ax{fill:var(--ink-3);font-size:11px;font-family:ui-monospace,monospace}
.lbl{font-size:12px;font-weight:700}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:11px}
.tile{background:var(--ground);border-radius:10px;padding:13px 15px}
.tile b{display:block;font-family:ui-monospace,monospace;font-size:27px;line-height:1.2;
 color:var(--accent)}
.tile span{font-size:12px;color:var(--ink-3)}
ul{margin:0;padding-left:1.2em}
li{margin-bottom:7px}
li b{color:var(--hot)}
.day{font-family:ui-monospace,monospace;font-size:12px;color:var(--ink-3);margin-right:7px}
.tbl{margin-top:9px}
.tbl summary{cursor:pointer;font-size:12.5px;color:var(--ink-3)}
.scroll{overflow-x:auto;margin-top:9px}
table{border-collapse:collapse;font-size:12px;font-family:ui-monospace,monospace}
th,td{border:1px solid var(--line);padding:4px 8px;text-align:right;white-space:nowrap}
thead th{background:var(--ground)}
tbody th{text-align:left;font-weight:700;font-family:inherit}
.dot{display:inline-block;width:9px;height:9px;border-radius:3px;margin-right:6px}
.none{color:var(--ink-3);font-size:13px;margin:4px 0}
.hint{background:var(--ground);border-radius:9px;padding:12px 15px;font-size:12.5px;
 color:var(--ink-2);margin-top:10px}
code{font-family:ui-monospace,monospace;font-size:12px}
"""


def build_html(month, days, chg, mov, rise, pv, hand):
    byday = sorted(days)
    tot_v = sum(d["totals"]["videos"] for d in days.values())
    tot_g = max((d["totals"]["games"] for d in days.values()), default=0)
    tot_c = max((d["totals"]["channels"] for d in days.values()), default=0)

    p = [f'<!doctype html><html lang="ja"><head><meta charset="utf-8">'
         f'<meta name="viewport" content="width=device-width,initial-scale=1">'
         f'<title>ハヤリゲー {month} 裏話レポート</title><style>{CSS}</style></head><body>'
         f'<div class="wrap"><h1>ハヤリゲー {month} 裏話レポート</h1>'
         f'<p class="sub">note用の下書きの材料です。サイトには載せない話をまとめています。'
         f'集計できた日数 {len(byday)}日</p>']

    if hand:
        p.append('<section><h2><span class="n">話の種</span>この月に起きたこと</h2>'
                 '<p class="note">直したときに書き残しておいたものです。'
                 'ここがnoteの柱になります。</p>')
        for x in hand:
            body = "".join(f'<p style="margin:5px 0">{md(b)}</p>' for b in x["body"])
            p.append(f'<div style="border-left:3px solid var(--hot);padding:2px 0 2px 13px;'
                     f'margin:14px 0"><div style="font-weight:700">'
                     f'<span class="day">{x["date"][5:]}</span>{e(x["title"])}</div>'
                     f'{body}</div>')
        p.append('</section>')

    p.append('<section><h2><span class="n">規模</span>この月の数字</h2>'
             f'<div class="tiles">'
             f'<div class="tile"><b>{tot_v:,}</b><span>のべ配信数</span></div>'
             f'<div class="tile"><b>{tot_g:,}</b><span>1日の最多ゲーム数</span></div>'
             f'<div class="tile"><b>{tot_c:,}</b><span>1日の最多チャンネル数</span></div>'
             f'<div class="tile"><b>{len(byday)}</b><span>集計できた日数</span></div>'
             '</div></section>')

    # PV
    p.append('<section><h2><span class="n">PV</span>アクセスの推移</h2>')
    if pv:
        labels = [d for d, _ in pv]
        p.append('<p class="note">Cloudflare Web Analytics の日別ページビュー。</p>')
        p.append(line_chart(labels, [{"name": "PV", "values": [v for _, v in pv]}], "PV"))
        tot = sum(v for _, v in pv)
        best = max(pv, key=lambda x: x[1])
        p.append(f'<div class="tiles" style="margin-top:12px">'
                 f'<div class="tile"><b>{tot:,}</b><span>月間PV</span></div>'
                 f'<div class="tile"><b>{tot//max(len(pv),1):,}</b><span>1日平均</span></div>'
                 f'<div class="tile"><b>{best[1]:,}</b><span>最高（{best[0][5:]}）</span></div>'
                 f'</div>')
    else:
        p.append('<p class="none">PVのデータがまだありません。</p>'
                 '<div class="hint">Cloudflareのダッシュボード → Web Analytics → '
                 '期間を1か月にして日別の数字をコピーし、<code>data/pv.csv</code> に'
                 '1行1日でこの形で貼ってください。次の月から自動でグラフになります。'
                 '<br><code>2026-10-01,312<br>2026-10-02,455</code></div>')
    p.append('</section>')

    # ランキングの動き
    p.append('<section><h2><span class="n">動き</span>ランキングで目についたこと</h2>')
    if mov["top"]:
        names = [t["game"] for t in mov["top"]][:4]
        ser = []
        for nm in names:
            vals = []
            for d in byday:
                hit = next((r for r in days[d]["ranking"] if r["game"] == nm), None)
                vals.append(hit["channels"] if hit else None)
            ser.append({"name": nm, "values": vals})
        p.append('<p class="note">この月いちばん多くの配信者が触ったゲーム4本の、'
                 '日ごとのチャンネル数。</p>')
        p.append(line_chart(byday, ser, "ch"))
    if mov["debut"]:
        p.append('<h3 style="font-size:14px;margin:18px 0 7px">この月に初めて入ったゲーム</h3>'
                 f'<p class="note">当サイトの記録は {all_days()[0] if all_days() else "—"} から'
                 'なので、それより前のことは分かりません。'
                 '「世の中で初めて」ではなく「当サイトの記録では初めて」です。</p><ul>')
        for x in mov["debut"][:8]:
            p.append(f'<li><span class="day">{x["day"][5:]}</span>'
                     f'<b>{e(x["game"])}</b> — 最多で {x["peak"]}チャンネル'
                     f'（{x["peak_day"][5:]}）</li>')
        p.append('</ul>')
    if mov["jumps"]:
        p.append('<h3 style="font-size:14px;margin:18px 0 7px">1日で大きく増えた日</h3><ul>')
        for x in mov["jumps"][:8]:
            p.append(f'<li><span class="day">{x["day"][5:]}</span>'
                     f'<b>{e(x["game"])}</b> — {e(x["from"])} → {x["to"]}ch'
                     f'（+{x["diff"]}）</li>')
        p.append('</ul>')
    p.append('</section>')

    # 急上昇
    p.append('<section><h2><span class="n">発掘</span>「今このゲームがアツい」に出たもの</h2>'
             '<p class="note">当時この欄に出ていたゲームを、記録ページの数字から'
             '計算し直したものです。小さいゲームが多いので、note向けの話が眠っています。</p>')
    if rise:
        p.append('<ul>')
        for x in rise[:10]:
            b = x["best"]
            p.append(f'<li><b>{e(x["game"])}</b> — {x["days"]}日出ました。'
                     f'いちばん伸びたのは<span class="day">{b["day"][5:]}</span>'
                     f'の ×{b["growth"]}（{b["videos"]}件 / {b["channels"]}ch）</li>')
        p.append('</ul>')
    else:
        p.append('<p class="none">この月は該当がありませんでした。</p>')
    p.append('</section>')

    # 運営の裏側
    p.append('<section><h2><span class="n">裏側</span>辞書を直した記録</h2>'
             '<p class="note">その月に判定用のファイルへ足した／消したものです。'
             'ここが「なぜ見落としていたか」の話の種になります。</p>')
    if chg:
        p.append('<ul>')
        for c in chg:
            p.append(f'<li><span class="day">{c["date"][5:]}</span>')
            bits = []
            for what, g in c["groups"].items():
                t = f'<b>{e(what)}</b>'
                if g["added"]:
                    more = f"（ほか{len(g['added'])-12}件）" if len(g["added"]) > 12 else ""
                    t += " … " + e("、".join(g["added"][:12])) + more
                if g["removed"]:
                    t += "<br>　戻した／消した: " + e("、".join(g["removed"][:8]))
                bits.append(t)
            p.append("<br>".join(bits) + "</li>")
        p.append('</ul>')
    else:
        p.append('<p class="none">この月は変更の記録が見つかりませんでした'
                 '（履歴が取れていないか、変更が無かった月です）。</p>')
    p.append('</section>')

    p.append('</div></body></html>')
    return "".join(p)


def digest(month, days, chg, mov, rise, pv, hand):
    """noteの本文を書くときに使う、文字だけの要約。"""
    o = [f"■ ハヤリゲー {month} 裏話レポート（集計 {len(days)}日）"]
    if hand:
        o.append("この月に起きたこと:")
        for x in hand:
            o.append(f"  {x['date']} {x['title']}")
    if pv:
        o.append(f"PV: 月間 {sum(v for _,v in pv):,} / 1日平均 "
                 f"{sum(v for _,v in pv)//max(len(pv),1):,}")
    else:
        o.append("PV: data/pv.csv が無いため未集計")
    if mov["top"]:
        o.append("最多: " + "、".join(f"{t['game']}({t['peak']}ch)" for t in mov["top"]))
    if mov["debut"]:
        o.append("初登場: " + "、".join(f"{x['game']}({x['day'][5:]})"
                                        for x in mov["debut"][:6]))
    if mov["jumps"]:
        o.append("急な伸び: " + "、".join(f"{x['game']} {x['from']}→{x['to']}ch({x['day'][5:]})"
                                          for x in mov["jumps"][:5]))
    if rise:
        o.append("急上昇欄の常連: " + "、".join(f"{x['game']}({x['days']}日)"
                                                for x in rise[:6]))
    if chg:
        o.append("辞書の変更:")
        for c in chg:
            for what, g in c["groups"].items():
                if g["added"]:
                    o.append(f"  {c['date']} {what}: " + "、".join(g["added"][:10]))
    return "\n".join(o)


def main():
    if len(sys.argv) < 2 or not re.fullmatch(r"\d{4}-\d{2}", sys.argv[1]):
        print("使い方: python scripts/monthly_notes.py 2026-09")
        return 2
    month = sys.argv[1]
    days = load_month(month)
    if not days:
        print(f"{month} の記録ページが見つかりません（site/d/{month}-*/）")
        return 1
    chg = dict_changes(month)
    mov = movements(month, days)
    rise = rising_again(month, days)
    pv = load_pv(month)
    hand = hand_notes(month)

    out = ROOT / f"note_{month}.html"
    out.write_text(build_html(month, days, chg, mov, rise, pv, hand), encoding="utf-8")
    log(f"書き出しました: {out}")

    # サイトの月まとめ用の材料を先に出す。こちらが本編（読みもの）の材料で、
    # 下の裏話レポートは note 用。混ざらないように区切りを入れておく。
    brief = column_brief(month, grew(month))
    bf = ROOT / f"月まとめの材料_{month}.txt"
    bf.write_text(brief + "\n", encoding="utf-8")
    log(f"書き出しました: {bf}")
    print(brief)
    print("\n" + "─" * 60 + "\n")
    print(digest(month, days, chg, mov, rise, pv, hand))
    return 0


if __name__ == "__main__":
    sys.exit(main())
