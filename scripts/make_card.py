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
body{width:1600px;height:900px;overflow:hidden;color:#E9F1F0;
  background:radial-gradient(1100px 640px at 92% -14%,#123C3E 0%,rgba(18,60,62,0) 60%),
             radial-gradient(820px 560px at -10% 106%,#2E1D13 0%,rgba(46,29,19,0) 58%),#0A1113;
  font-family:"Zen Kaku Gothic New","Hiragino Kaku Gothic ProN","Noto Sans JP",sans-serif;
  padding:44px 56px 34px;display:flex;flex-direction:column}
header{display:flex;align-items:flex-start;gap:22px;padding-bottom:20px;border-bottom:2px solid #24393B}
.mark{width:62px;height:62px;flex:none;object-fit:contain}
h1{font-size:40px;font-weight:900;line-height:1.05}
.sub{font-size:19px;color:#8FA9AB;margin-top:7px;font-weight:500}
.meta{margin-left:auto;text-align:right;flex:none}
.meta .d{font-family:"Roboto Mono",monospace;font-size:34px;font-weight:700;color:#4FC9CD;line-height:1}
.meta .c{font-size:15px;color:#8FA9AB;margin-top:9px;line-height:1.6}
.body{flex:1;display:grid;grid-template-columns:660px 1fr;gap:44px;padding-top:24px;min-height:0}
.col{display:flex;flex-direction:column}
.col .badge{align-self:flex-start;font-family:"Roboto Mono",monospace;font-size:12px;letter-spacing:.12em;
  font-weight:700;color:#0A1113;background:#E8975C;padding:5px 12px;border-radius:6px}
.col h2{font-size:31px;font-weight:900;margin-top:14px;line-height:1.25}
.col .hl{font-size:19px;font-weight:700;color:#E8975C;margin-top:9px;line-height:1.45}
.col p{font-size:16.5px;line-height:1.95;color:#BDD2D2;margin-top:14px}
.col .who{display:flex;flex-wrap:wrap;gap:7px;margin-top:16px}
.col .who span{font-size:13.5px;color:#9FB8B9;background:#15282A;border:1px solid #24393B;
  border-radius:16px;padding:4px 12px}
.col .src{font-size:12.5px;color:#6E8688;margin-top:15px;line-height:1.7}
.pitch{margin-top:auto;padding:18px 22px;border-radius:12px;background:#102A2C;
  border:1px solid #1F4547;border-left:4px solid #4FC9CD}
.pitch b{display:block;font-size:22px;font-weight:900;color:#8FE4E7;line-height:1.4}
.pitch span{display:block;font-size:14px;color:#8FA9AB;margin-top:7px;line-height:1.7}
.rank h3{font-family:"Roboto Mono",monospace;font-size:12px;letter-spacing:.14em;color:#8FA9AB;
  font-weight:500;padding-bottom:11px;border-bottom:1px solid #24393B}
.row{display:flex;align-items:center;gap:16px;padding:14px 0;border-bottom:1px solid #17282A}
.rk{font-family:"Roboto Mono",monospace;font-size:20px;font-weight:700;color:#5B7476;width:34px;text-align:right;flex:none}
.row.top .rk{color:#E8975C}
.nm{font-size:18px;font-weight:700;width:290px;flex:none;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bar{flex:1;height:9px;background:#16282A;border-radius:5px;overflow:hidden}
.bar i{display:block;height:100%;background:linear-gradient(90deg,#0E7E84,#4FC9CD);border-radius:5px}
.row.top .bar i{background:linear-gradient(90deg,#B4551C,#E8975C)}
.ct{font-family:"Roboto Mono",monospace;font-size:15px;color:#9FB8B9;width:126px;text-align:right;flex:none}
.ct em{font-style:normal;font-size:12px;color:#6E8688;margin:0 1px}
footer{display:flex;align-items:center;gap:18px;padding-top:16px;border-top:1px solid #1D3032;margin-top:14px}
.note{font-size:13px;color:#6E8688;line-height:1.7}
.url{margin-left:auto;font-family:"Roboto Mono",monospace;font-size:20px;font-weight:700;color:#4FC9CD;
  background:#102A2C;border:1px solid #1F4547;border-radius:9px;padding:9px 18px;white-space:nowrap}
"""

PAGE = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Zen+Kaku+Gothic+New:wght@500;700;900&family=Noto+Sans+JP:wght@500;700;900&family=Roboto+Mono:wght@500;700&display=swap">
<style>%(css)s</style></head><body>
<header>
  <img class="mark" src="logo.svg" alt="">
  <div><h1>ハヤリゲー</h1><div class="sub">VTuber・ゲーム実況者が、いま配信しているゲーム</div></div>
  <div class="meta"><div class="d">%(date)s</div>
    <div class="c">直近24時間 ／ 配信 %(videos)s本 ／ %(channels)sチャンネル<br>検出ゲーム %(games)s種</div></div>
</header>
<div class="body">
  <section class="col">%(column)s
    <div class="pitch"><b>次、何のゲーム配信する？</b>
      <span>配信するゲームを選ぶための、毎日更新のランキングです。</span></div>
  </section>
  <section class="rank"><h3>TOP%(n)s ／ 配信数・配信者数・再生数の総合スコア順</h3><div>%(rows)s</div></section>
</div>
<footer>
  <div class="note">%(note)s</div>
  <span class="url">%(url)s</span>
</footer>
</body></html>
"""


def e(s):
    return html.escape(str(s or ""))


def column_html(col):
    if not col:
        return ('<span class="badge">今日のランキング</span>'
                '<h2 style="margin-top:18px">今日は特筆すべき動きがありません</h2>'
                '<p>コラムは、複数の配信者が同じ企画に参加したり、'
                '新しいゲームが急に広がったりした日に書いています。'
                '書くことが無い日は無理に書きません。</p>')
    who = "".join(f"<span>{e(p)}</span>" for p in (col.get("people") or [])[:9])
    src = "・".join(e(s.get("t", "")) for s in (col.get("sources") or [])[:3])
    return (f'<span class="badge">今日の注目ゲーム</span>'
            f'<h2>{e(col.get("game"))}</h2>'
            f'<div class="hl">{e(col.get("headline"))}</div>'
            f'<p>{e(col.get("body"))}</p>'
            + (f'<div class="who">{who}</div>' if who else "")
            + (f'<div class="src">出典：{src}</div>' if src else ""))


def rows_html(ranking):
    rows = ranking[:TOP_N]
    if not rows:
        return '<div class="row"><span class="nm">データがありません</span></div>'
    top = max((r.get("score") or 0) for r in rows) or 1
    out = []
    for i, r in enumerate(rows):
        w = max(4, (r.get("score") or 0) / top * 100)
        out.append(
            f'<div class="row{" top" if i < 3 else ""}">'
            f'<span class="rk">{i + 1}</span>'
            f'<span class="nm">{e(r.get("game"))}</span>'
            f'<span class="bar"><i style="width:{w:.1f}%"></i></span>'
            f'<span class="ct">{r.get("videos", 0)}<em>件</em>・{r.get("channels", 0)}<em>ch</em></span>'
            f'</div>')
    return "".join(out)


def build(data):
    t = data.get("totals") or {}
    note = ("YouTubeの配信タイトルを毎日自動で解析／同じ配信者の連番シリーズは1件として集計<br>"
            "Shorts・切り抜きは対象外")
    return PAGE % {
        "css": CSS,
        "date": e(str(data.get("date", "")).replace("-", ".")),
        "videos": t.get("videos", 0), "channels": t.get("channels", 0),
        "games": t.get("games", 0), "n": TOP_N,
        "column": column_html(data.get("column")),
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
