#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""その日のコラムとランキングを1枚の画像（1600×900）にする。

site/data.json を読んで site/card.html を書き出すところまでを行う。
画像への変換は Playwright（ヘッドレスChrome）で行う:

    python scripts/make_card.py            # card.html を作る
    python scripts/make_card.py --png      # 画像まで作る（Playwrightが必要）

Xに貼る前提なので、リンクを踏まなくてもURLが読めるよう画像内にも入れてある。
"""
import html
import json
import sys
from pathlib import Path

from common import SITE, log, read_json

SITE_URL = "hayarige.tarochin1985.workers.dev"
TOP_N = 10

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{width:1600px;height:900px;overflow:hidden;color:#EAF2F1;
  background:radial-gradient(1200px 780px at 78% -22%,#154A4E 0%,rgba(21,74,78,0) 62%),
             radial-gradient(760px 560px at -6% 112%,#3A2411 0%,rgba(58,36,17,0) 58%),#080F11;
  font-family:"Zen Kaku Gothic New","Hiragino Kaku Gothic ProN","Noto Sans JP",sans-serif;
  padding:44px 54px 40px;display:flex;flex-direction:column}

header{display:flex;align-items:center;gap:18px;flex:none}
header img{width:52px;height:52px;object-fit:contain}
header .nm{font-size:30px;font-weight:900;letter-spacing:.01em}
header .tag{font-size:16px;color:#8FADAE;margin-left:2px}
header .meta{margin-left:auto;text-align:right}
header .d{font-family:"Roboto Mono",monospace;font-size:30px;font-weight:700;color:#5FD8DC;line-height:1}
header .c{font-size:14px;color:#8FADAE;margin-top:7px}

.body{flex:1;display:grid;grid-template-columns:1fr 520px;gap:46px;padding-top:26px;min-height:0}

/* 左：今日いちばん言いたいこと。1枚の画像として、まずここが読まれる */
.lead{display:flex;flex-direction:column;min-width:0}
.eye{align-self:flex-start;display:flex;align-items:center;gap:9px;
  font-size:15px;font-weight:900;color:#0A1113;background:#F0A163;
  padding:6px 15px 6px 13px;border-radius:7px;letter-spacing:.02em}
.eye svg{width:17px;height:17px}
.game{font-size:62px;font-weight:900;line-height:1.14;margin-top:20px;letter-spacing:-.02em;
  text-wrap:balance}
.game.long{font-size:50px}
.game.xlong{font-size:42px}
.hl{font-size:26px;font-weight:700;line-height:1.55;color:#F0A163;margin-top:20px}
.hl.long{font-size:23px}
.who{display:flex;flex-wrap:wrap;gap:8px;margin-top:22px}
.who span{font-size:16px;color:#B7CFD0;background:#12262A;border:1px solid #24444A;
  border-radius:20px;padding:6px 15px}
/* 7日分の棒グラフ。数字より形のほうが速く伝わる */
.trend{margin-top:auto}
.trend .cap{font-size:15px;color:#7E9A9B;display:flex;align-items:baseline;gap:14px}
.trend .cap b{font-family:"Roboto Mono",monospace;font-size:19px;color:#F0A163;font-weight:700}
.trend .bars{display:flex;align-items:flex-end;gap:12px;height:190px;margin-top:16px}
.trend .b{flex:1;height:100%;display:flex;flex-direction:column;justify-content:flex-end;
  align-items:stretch;gap:8px}
.trend .b i{display:block;background:#1C3C40;border-radius:5px 5px 2px 2px}
.trend .b.on i{background:linear-gradient(180deg,#F0A163,#B4551C)}
.trend .b em{font-style:normal;font-family:"Roboto Mono",monospace;font-size:12px;
  color:#5F7B7D;text-align:center}
.trend .b.on em{color:#F0A163;font-weight:700}

.pitch{margin-top:30px;display:flex;align-items:center;gap:16px}
.pitch b{font-size:26px;font-weight:900;color:#8FE9EC}
.pitch span{font-size:15px;color:#7E9A9B}

/* 右：ランキング。数字を大きく、順位の差が形で分かるように */
.rank{display:flex;flex-direction:column;min-width:0}
.rank h3{font-size:15px;font-weight:900;color:#8FADAE;padding-bottom:14px;
  border-bottom:2px solid #1E3639;display:flex;align-items:baseline;gap:10px}
.rank h3 em{font-style:normal;font-size:12.5px;font-weight:500;color:#5F7B7D}
.row{display:grid;grid-template-columns:44px 1fr auto;align-items:center;gap:12px;
  padding:11px 0 10px;border-bottom:1px solid #16282B}
.row .rk{font-family:"Roboto Mono",monospace;font-size:30px;font-weight:700;
  color:#3E5A5D;text-align:center;line-height:1}
.row.t1 .rk{color:#F0A163;font-size:38px}
.row.t2 .rk,.row.t3 .rk{color:#7FA3A5}
.row .nm{font-size:21px;font-weight:700;overflow:hidden;text-overflow:ellipsis;
  white-space:nowrap}
.row.t1 .nm{font-size:25px}
.row .bar{grid-column:2;height:7px;background:#132528;border-radius:4px;overflow:hidden;
  margin-top:9px}
.row .bar i{display:block;height:100%;border-radius:4px;
  background:linear-gradient(90deg,#0E8B90,#5FD8DC)}
.row.t1 .bar i{background:linear-gradient(90deg,#B4551C,#F0A163)}
.row .ct{font-family:"Roboto Mono",monospace;font-size:17px;color:#9CB8B9;text-align:right;
  white-space:nowrap}
.row .ct em{font-style:normal;font-size:13px;color:#63807F}
.row.t1 .ct{font-size:20px;color:#EAF2F1}

footer{flex:none;display:flex;align-items:center;gap:20px;padding-top:22px;
  border-top:1px solid #1A2E31;margin-top:20px}
.note{font-size:13.5px;color:#63807F;line-height:1.7}
.url{margin-left:auto;font-family:"Roboto Mono",monospace;font-size:21px;font-weight:700;
  color:#08191A;background:#5FD8DC;border-radius:9px;padding:11px 20px;white-space:nowrap}
"""

PAGE = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Zen+Kaku+Gothic+New:wght@500;700;900&family=Noto+Sans+JP:wght@500;700;900&family=Roboto+Mono:wght@500;700&display=swap">
<style>%(css)s</style></head><body>
<header>
  <img src="logo.svg" alt="">
  <span class="nm">ハヤリゲー</span>
  <span class="tag">VTuber・ゲーム実況者が、いま配信しているゲーム</span>
  <div class="meta"><div class="d">%(date)s</div>
    <div class="c">直近24時間 ／ 配信 %(videos)s本 ／ %(channels)sチャンネル</div></div>
</header>
<div class="body">
  <section class="lead">%(lead)s
    <div class="pitch"><b>次、何のゲーム配信する？</b>
      <span>毎日更新のランキングです</span></div>
  </section>
  <section class="rank">
    <h3>今日のTOP7<em>配信者数・再生数・配信数から算出</em></h3>
    %(rows)s
  </section>
</div>
<footer>
  <div class="note">%(note)s</div>
  <span class="url">%(url)s</span>
</footer>
</body></html>
"""


def e(s):
    return html.escape(str(s or ""))


def man(n):
    n = int(n or 0)
    if n >= 100000:
        return f"{n // 10000}万"
    if n >= 10000:
        return f"{n / 10000:.1f}万"
    return f"{n:,}"


BOLT = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M13 2L4 14h7l-1 8 9-12h-7l1-8z"/></svg>')


def size_class(text, small, smaller):
    n = len(text or "")
    return " xlong" if n > smaller else (" long" if n > small else "")


def trend_html(game, ranking, days):
    """取り上げたゲームの7日分を、大きな棒グラフで出す。

    「なぜ今日これなのか」は、言葉より形のほうが速い。
    倍率だけだと1件が3件でも×3になってしまうので、実数も添える。
    """
    row = next((r for r in ranking if r.get("game") == game), None)
    spark = (row or {}).get("spark") or []
    vals = [v for v in spark if v is not None]
    if not row or len(vals) < 3 or max(vals) < 2:
        return ""
    top = max(vals) or 1
    bars = []
    for i, v in enumerate(spark):
        h = 0 if v is None else max(3, round(v / top * 100))
        last = i == len(spark) - 1
        d = (days or [])[i] if i < len(days or []) else ""
        bars.append(f'<span class="b{" on" if last else ""}">'
                    f'<i style="height:{h}%"></i><em>{e(d[-5:])}</em></span>')
    base = row.get("base")
    cap = (f'ふだん {base:g}件 → 今日 {row.get("videos", 0)}件'
           if base is not None else f'今日 {row.get("videos", 0)}件')
    return (f'<div class="trend"><div class="cap">この7日間の配信数'
            f'<b>{e(cap)}</b></div><div class="bars">{"".join(bars)}</div></div>')


def lead_html(col, ranking, days=None):
    """左半分。その日いちばん言いたいことを、大きな字で1つだけ置く。

    以前はコラムの本文をそのまま流し込んでいたが、タイムラインでは
    幅400pxほどに縮むので、あの大きさの文字は誰にも読まれない。
    画像で伝えるのは「どのゲームか」と「なぜか」の一行まで。
    本文はサイトで読んでもらう。
    """
    if col:
        return (f'<span class="eye">{BOLT}今日の注目ゲーム</span>'
                f'<div class="game{size_class(col.get("game"), 14, 22)}">{e(col.get("game"))}</div>'
                f'<div class="hl{size_class(col.get("headline"), 40, 999)}">'
                f'{e(col.get("headline"))}</div>'
                + ('<div class="who">'
                   + "".join(f"<span>{e(x)}</span>" for x in (col.get("people") or [])[:7])
                   + "</div>" if col.get("people") else "")
                + trend_html(col.get("game"), ranking, days))
    # コラムが無い日は、1位のゲームを立てる
    top = (ranking or [{}])[0]
    return (f'<span class="eye">{BOLT}今日いちばん配信されたゲーム</span>'
            f'<div class="game{size_class(top.get("game"), 14, 22)}">{e(top.get("game"))}</div>'
            f'<div class="hl">{top.get("channels", 0)}チャンネルが配信、'
            f'{man(top.get("views"))}回 再生されました</div>')


def rows_html(ranking):
    rows = ranking[:7]
    if not rows:
        return '<div class="row"><span class="nm">データがありません</span></div>'
    top = max((r.get("videos") or 0) for r in rows) or 1
    out = []
    for i, r in enumerate(rows):
        w = max(6, (r.get("videos") or 0) / top * 100)
        cls = f" t{i + 1}" if i < 3 else ""
        out.append(
            f'<div class="row{cls}">'
            f'<span class="rk">{i + 1}</span>'
            f'<span class="nm">{e(r.get("game"))}</span>'
            f'<span class="ct">{r.get("videos", 0)}<em>件</em> '
            f'{r.get("channels", 0)}<em>ch</em></span>'
            f'<span class="bar"><i style="width:{w:.0f}%"></i></span>'
            f"</div>")
    return "".join(out)


def build(data):
    t = data.get("totals") or {}
    note = ("YouTubeの配信タイトルを毎日自動で解析しています<br>"
            "Shorts・切り抜きは対象外／同じ配信者が同じ日に出した続きものは1件として集計")
    return PAGE % {
        "css": CSS,
        "date": e(str(data.get("date", "")).replace("-", ".")),
        "videos": t.get("videos", 0), "channels": t.get("channels", 0),
        "lead": lead_html(data.get("column"), data.get("ranking") or [],
                          data.get("days") or []),
        "rows": rows_html(data.get("ranking") or []),
        "note": note, "url": SITE_URL,
    }

def main():
    data = read_json(SITE / "data.json", None)
    if not data:
        log("site/data.json がありません。先に build_site.py を動かしてください。")
        return 1
    out = SITE / "card.html"
    out.write_text(build(data), encoding="utf-8")
    log(f"カードを書き出しました: {out}")

    if "--png" in sys.argv:
        from playwright.sync_api import sync_playwright
        png = SITE / "card.png"
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": 1600, "height": 900},
                            device_scale_factor=1)
            pg.goto("file://" + str(out.resolve()))
            pg.wait_for_timeout(1200)          # フォントの読み込み待ち
            pg.screenshot(path=str(png))
            b.close()
        log(f"画像を書き出しました: {png}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
