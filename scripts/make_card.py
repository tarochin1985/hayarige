#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""その日のコラムとランキングを1枚の画像（1600×900）にする。

site/data.json を読んで site/card.html を書き出すところまでを行う。
画像への変換は Playwright（ヘッドレスChrome）で行う:

    python scripts/make_card.py            # card.html を作る
    python scripts/make_card.py --png      # 画像まで作る（Playwrightが必要）

見た目は6種類から選べる。data/site_config.json の card_theme で決まる。
その場で見比べたいときは --theme= を付ける:

    python scripts/make_card.py --png --theme=pop --out=card_pop

Xに貼る前提なので、リンクを踏まなくてもURLが読めるよう画像内にも入れてある。
"""
import html
import json
import re
import sys
from pathlib import Path

from common import SITE, log, read_json

SITE_URL = "hayarige.tarochin1985.workers.dev"
TOP_N = 10

# ---------------------------------------------------------------- 見た目
# 配色と書体をまとめて差し替えられるようにしてある。
#     python scripts/make_card.py --png --theme=pop
# どれを使うかは data/site_config.json の card_theme でも指定できる。
# (Google Fontsへの指定, CSSの書体指定, 見出しに使う太さ)
# 3つめが要る理由: Dela Gothic One と RocknRoll One は太さが1種類しかない。
# そこに font-weight:900 を当てるとブラウザが勝手に太らせて字が潰れる。
FONTS = {
    "gothic": ('Zen+Kaku+Gothic+New:wght@500;700;900',
               '"Zen Kaku Gothic New","Hiragino Kaku Gothic ProN",sans-serif', 900),
    "round":  ('Zen+Maru+Gothic:wght@500;700;900',
               '"Zen Maru Gothic","Hiragino Maru Gothic ProN",sans-serif', 900),
    "mplus":  ('M+PLUS+Rounded+1c:wght@500;700;800;900',
               '"M PLUS Rounded 1c","Hiragino Maru Gothic ProN",sans-serif', 900),
    "dela":   ('Dela+Gothic+One', '"Dela Gothic One",sans-serif', 400),
    "rock":   ('RocknRoll+One', '"RocknRoll One",sans-serif', 400),
}

# 各テーマの意味:
#   title/text … 使う書体（FONTS のキー）
#   bg         … 背景。ink〜on は文字と枠の色
#   sum        … 3行要約の色。ゲーム名（hot）と変えて視線の順番を作る
#   stroke     … ゲーム名と数字につけるフチの太さ。"" ならフチなし
#   strokec    … フチの色。明るい地なら濃い色、白フチにしたいなら白
THEMES = {
    # いまのダークを、書体だけポップに寄せたもの
    "dark": {
        "title": "dela", "text": "round",
        "bg": ("radial-gradient(1200px 800px at 74% -24%,#154A4E 0%,rgba(21,74,78,0) 60%),"
               "radial-gradient(720px 540px at -6% 114%,#3A2411 0%,rgba(58,36,17,0) 56%),#070E10"),
        "ink": "#EAF2F1", "ink2": "#8FADAE", "ink3": "#5F7B7D",
        "card": "rgba(12,26,29,.72)", "line": "#1D3639", "rail": "#132528",
        "accent": "#5FD8DC", "hot": "#F0A163", "on": "#0A1113",
        "sum": "#EAF2F1", "stroke": "", "strokec": "#070E10",
    },
    # 明るいクリーム地。落ち着いた紙もの寄りだが、ゲーム名はフチで立たせる
    "cream": {
        "title": "dela", "text": "round",
        "bg": ("radial-gradient(1100px 760px at 78% -20%,#FFE7CE 0%,rgba(255,231,206,0) 62%),"
               "radial-gradient(760px 560px at -6% 112%,#D9F0EE 0%,rgba(217,240,238,0) 58%),#FBF7F1"),
        "ink": "#1A2426", "ink2": "#5B7375", "ink3": "#8AA0A1",
        "card": "rgba(255,255,255,.82)", "line": "#E3DACE", "rail": "#EDE5DA",
        "accent": "#0E8B90", "hot": "#E2620F", "on": "#FFFFFF",
        "sum": "#1A2426", "stroke": "4px", "strokec": "#2A1A0E",
    },
    # 白地・高コントラスト。ゲーム名に濃いフチ。配信のサムネイルに近い出方
    "pop": {
        "title": "dela", "text": "mplus",
        "bg": ("radial-gradient(900px 620px at 88% -18%,#BFF3F2 0%,rgba(191,243,242,0) 58%),"
               "radial-gradient(820px 600px at -8% 110%,#FFDCC0 0%,rgba(255,220,192,0) 56%),#FFFFFF"),
        "ink": "#10191B", "ink2": "#4E6668", "ink3": "#809394",
        "card": "#FFFFFF", "line": "#DCE6E5", "rail": "#E8EFEE",
        "accent": "#0B7E83", "hot": "#F0521B", "on": "#FFFFFF",
        "sum": "#10191B", "stroke": "4px", "strokec": "#10191B",
    },
    # パステル。丸ゴシックでやわらかく、フチは濃い紫で締める
    "candy": {
        "title": "round", "text": "mplus",
        "bg": ("radial-gradient(980px 700px at 84% -18%,#CFF3E6 0%,rgba(207,243,230,0) 60%),"
               "radial-gradient(860px 640px at -8% 112%,#FFD9E6 0%,rgba(255,217,230,0) 58%),#FFFBF6"),
        "ink": "#241E2B", "ink2": "#6B6076", "ink3": "#9C93A6",
        "card": "rgba(255,255,255,.88)", "line": "#EADFE8", "rail": "#F1E8EF",
        "accent": "#1E9E8A", "hot": "#E8437F", "on": "#FFFFFF",
        "sum": "#241E2B", "stroke": "4px", "strokec": "#2E2137",
    },
    # 黄色地。タイムラインでいちばん目に入る。サムネ寄せの最右翼
    "sun": {
        "title": "dela", "text": "mplus",
        "bg": ("radial-gradient(1000px 700px at 84% -20%,#FFE44D 0%,rgba(255,228,77,0) 62%),"
               "radial-gradient(880px 640px at -8% 112%,#FFB03A 0%,rgba(255,176,58,0) 58%),#FFF3C4"),
        "ink": "#1B1405", "ink2": "#6A5A2E", "ink3": "#94834F",
        "card": "rgba(255,255,255,.88)", "line": "#E8D79A", "rail": "#F2E6B8",
        "accent": "#0E7C6B", "hot": "#E23A0E", "on": "#FFFFFF",
        "sum": "#1B1405", "stroke": "4px", "strokec": "#1B1405",
    },
    # 濃い色地にフチ付き。いちばん賑やか
    "vivid": {
        "title": "dela", "text": "mplus",
        "bg": ("radial-gradient(1000px 700px at 82% -20%,#1C6F74 0%,rgba(28,111,116,0) 58%),"
               "radial-gradient(820px 620px at -8% 112%,#8A3D12 0%,rgba(138,61,18,0) 56%),#0E1A1D"),
        "ink": "#FFFFFF", "ink2": "#A9C6C7", "ink3": "#7C9899",
        "card": "rgba(10,24,27,.6)", "line": "#2A4A4E", "rail": "#162C30",
        "accent": "#57E3E8", "hot": "#FFC24A", "on": "#0A1113",
        "sum": "#FFFFFF", "stroke": "5px", "strokec": "#08181B",
    },
}

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{width:1600px;height:900px;overflow:hidden;color:var(--ink);background:%(bg)s;
  font-family:%(textfont)s;padding:34px 44px 30px;display:flex;flex-direction:column;gap:22px}

header{display:flex;align-items:center;gap:16px;flex:none}
header img{width:48px;height:48px;object-fit:contain}
header .nm{font-family:%(titlefont)s;font-weight:%(titleweight)s;font-size:28px;color:var(--ink)}
header .tag{font-size:15px;color:var(--ink2);font-weight:700}
header .meta{margin-left:auto;text-align:right}
header .d{font-family:"Roboto Mono",monospace;font-size:27px;font-weight:700;
  color:var(--accent);line-height:1}
header .c{font-size:13px;color:var(--ink2);margin-top:6px;font-weight:700}

.body{flex:1;display:grid;grid-template-columns:1fr 560px;gap:26px;min-height:0}
.card{background:var(--card);border:1px solid var(--line);border-radius:18px;
  padding:24px 26px;display:flex;flex-direction:column;min-height:0}
.eye{align-self:flex-start;display:inline-flex;align-items:center;gap:8px;
  font-family:%(titlefont)s;font-weight:%(titleweight)s;font-size:16px;color:var(--on);background:var(--hot);
  padding:6px 14px 6px 12px;border-radius:8px}
.eye svg{width:16px;height:16px}
.eye.tealx{background:var(--accent)}

.lead{display:flex;flex-direction:column;min-width:0;overflow:hidden}
.game{font-family:%(titlefont)s;font-weight:%(titleweight)s;font-size:72px;line-height:1.16;
  margin-top:14px;letter-spacing:-.01em;color:var(--hot)%(gamestroke)s}
.game.long{font-size:59px}
.game.xlong{font-size:49px}

/* 見出し。ゲーム名（hot）と本文（ink）の間を、色でもう1段つなぐ。 */
.hl{margin-top:14px;font-size:26px;font-weight:900;line-height:1.4;color:var(--accent)}

/* 本文。コラムは日によって120〜480字と幅があるので、
   入りきる大きさを描画してから決める（下の fit() を見てください）。 */
.txt{margin-top:14px;font-size:26px;font-weight:700;line-height:1.6;color:var(--sum)}

/* 本文が短い日は下に余白ができる。上下に均等に振って、
   サムネイルが宙に浮いて見えないようにする。 */
.pics{margin:auto 0 2px;padding-top:18px;display:flex;gap:16px}
.pics figure{width:232px;flex:none}
.pics.sm figure{width:186px}
.pics figure img{width:100%%;aspect-ratio:16/9;object-fit:cover;border-radius:10px;
  border:1px solid var(--line);display:block;background:var(--rail)}
.pics figcaption{font-size:12px;color:var(--ink3);margin-top:6px;line-height:1.45;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:700}
.pics.sm figcaption{font-size:11px}

.side{display:grid;grid-template-rows:1fr 1fr;gap:26px;min-height:0}
.row{display:grid;grid-template-columns:42px 1fr auto;align-items:center;gap:12px;
  padding:14px 0 12px;border-bottom:1px solid var(--line)}
.row:last-child{border-bottom:none}
.row .rk{font-family:%(titlefont)s;font-weight:%(titleweight)s;font-size:32px;color:var(--ink3);text-align:center;line-height:1}
.row.t1 .rk{color:var(--hot);font-size:40px}
.row .nm{font-size:24px;font-weight:800;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.row .ct{font-family:"Roboto Mono",monospace;font-size:17px;color:var(--ink2);white-space:nowrap}
.row .ct em{font-style:normal;font-size:13px;color:var(--ink3)}
.row .bar{grid-column:2/4;height:7px;background:var(--rail);border-radius:4px;
  overflow:hidden;margin-top:8px}
.row .bar i{display:block;height:100%%;border-radius:4px;background:var(--accent)}
.row.t1 .bar i{background:var(--hot)}

.hot{display:flex;flex-direction:column}
.hot .g{font-family:%(titlefont)s;font-weight:%(titleweight)s;font-size:32px;margin-top:14px;line-height:1.25;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--ink)}
.hot .delta{display:flex;align-items:baseline;gap:12px;margin-top:12px}
.hot .delta b{font-family:%(titlefont)s;font-weight:%(titleweight)s;font-size:44px;
  color:var(--hot);line-height:1%(numstroke)s}
.hot .delta span{font-size:16px;color:var(--ink2);font-weight:700}
.bars{display:flex;align-items:flex-end;gap:9px;height:104px;margin-top:auto}
.bars .b{flex:1;display:flex;flex-direction:column;justify-content:flex-end;gap:6px;height:100%%}
.bars .b i{display:block;background:var(--rail);border-radius:5px 5px 2px 2px}
.bars .b.on i{background:var(--hot)}
.bars .b em{font-style:normal;font-family:"Roboto Mono",monospace;font-size:11px;
  color:var(--ink3);text-align:center;font-weight:700}
.bars .b.on em{color:var(--hot)}

footer{flex:none;display:flex;align-items:center;gap:20px}
.note{font-size:13px;color:var(--ink3);line-height:1.7;font-weight:700}
.url{margin-left:auto;font-family:"Roboto Mono",monospace;font-size:20px;font-weight:700;
  color:var(--on);background:var(--accent);border-radius:10px;padding:10px 19px;white-space:nowrap}
"""

PAGE = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=%(fontq)s&family=Roboto+Mono:wght@500;700&display=swap">
<style>:root{%(vars)s}
%(css)s</style></head><body>
<header>
  <img src="logo.svg" alt="">
  <span class="nm">ハヤリゲー</span>
  <span class="tag">VTuber・ゲーム実況者が、いま配信しているゲーム</span>
  <div class="meta"><div class="d">%(date)s</div>
    <div class="c">直近24時間 ／ 配信 %(videos)s本 ／ %(channels)sチャンネル</div></div>
</header>
<div class="body">
  <section class="card lead">%(lead)s</section>
  <div class="side">
    <section class="card rank">
      <span class="eye tealx">%(crown)s今日のランキング</span>
      %(rows)s
    </section>
    <section class="card hot">%(hot)s</section>
  </div>
</div>
<footer>
  <div class="note">%(note)s</div>
  <span class="url">%(url)s</span>
</footer>
<script>%(fit)s</script>
</body></html>
"""

# コラムの本文は日によって120〜480字と長さが変わる。
# 文字数から大きさを決め打ちすると、見出しが2行になった日などにはみ出す。
# 実際に描いてから、入りきるまで1段ずつ小さくするほうが確実。
# 書体が届く前に測ると行数がずれるので、必ず fonts.ready を待つ。
# 先に本文を21.5pxまで落とし、それでも入らなければサムネイルを縮める。
# 読めない大きさの本文より、小さいサムネイルのほうがましだという判断。
FIT = """
document.fonts.ready.then(function(){
  var lead=document.querySelector('.lead'),t=lead&&lead.querySelector('.txt'),
      pics=lead&&lead.querySelector('.pics');
  if(!t) return;
  function fits(){ return lead.scrollHeight<=lead.clientHeight+1; }
  function step(sizes){
    for(var i=0;i<sizes.length;i++){ t.style.fontSize=sizes[i]+'px'; if(fits()) return true; }
    return false;
  }
  if(step([26,25,24,23,22,21])) return;
  if(pics) pics.classList.add('sm');
  step([21,20,19,18,17,16,15]);
});
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


def ico(path):
    return ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" '
            f'stroke-linecap="round" stroke-linejoin="round">{path}</svg>')


BOLT = ico('<path d="M13 2L4 14h7l-1 8 9-12h-7l1-8z"/>')
CROWN = ico('<path d="M3 18h18M4 6l4 4 4-6 4 6 4-4-2 10H6z"/>')
UP = ico('<path d="M4 17l6-6 4 4 6-8"/><path d="M15 7h5v5"/>')




def bars_html(spark, days):
    vals = [v for v in spark if v is not None]
    if len(vals) < 3:
        return ""
    top = max(vals) or 1
    out = []
    for i, v in enumerate(spark):
        h = 0 if v is None else max(3, round(v / top * 100))
        last = i == len(spark) - 1
        d = (days or [])[i] if i < len(days or []) else ""
        out.append(f'<span class="b{" on" if last else ""}">'
                   f'<i style="height:{h}%"></i><em>{e(d[-5:])}</em></span>')
    return f'<div class="bars">{"".join(out)}</div>'


def size_class(text, small, smaller):
    n = len(text or "")
    return " xlong" if n > smaller else (" long" if n > small else "")


def lead_html(col, ranking):
    """左半分。コラムの中身をここで見せきる。"""
    if not col:
        top = (ranking or [{}])[0]
        return (f'<span class="eye">{BOLT}今日いちばん配信されたゲーム</span>'
                f'<div class="game{size_class(top.get("game"), 13, 20)}">{e(top.get("game"))}</div>'
                f'<div class="hl">{top.get("channels", 0)}チャンネルが配信しました</div>'
                f'<p class="txt">再生数は合わせて {man(top.get("views"))}回。</p>')
    game = str(col.get("game") or "")
    head = str(col.get("headline") or "")
    body = str(col.get("body") or "")
    pics = col.get("pics") or ([{"th": col["hero"], "by": col.get("hero_by", "")}]
                               if col.get("hero") else [])
    figs = "".join(f'<figure><img src="{e(x["th"])}" alt="">'
                   f'<figcaption>YouTube ／ {e(x.get("by"))}</figcaption></figure>'
                   for x in pics[:3])
    return (f'<span class="eye">{BOLT}今日の注目ゲーム</span>'
            f'<div class="game{size_class(game, 13, 20)}">{e(game)}</div>'
            + (f'<div class="hl">{e(head)}</div>' if head else "")
            + f'<p class="txt">{e(body)}</p>'
            + (f'<div class="pics">{figs}</div>' if figs else ""))


def rows_html(ranking):
    rows = ranking[:3]
    if not rows:
        return '<div class="row"><span class="nm">データがありません</span></div>'
    top = max((r.get("videos") or 0) for r in rows) or 1
    out = []
    for i, r in enumerate(rows):
        w = max(8, (r.get("videos") or 0) / top * 100)
        out.append(
            f'<div class="row{" t1" if i == 0 else ""}">'
            f'<span class="rk">{i + 1}</span>'
            f'<span class="nm">{e(r.get("game"))}</span>'
            f'<span class="ct">{r.get("videos", 0)}<em>件</em> {r.get("channels", 0)}<em>ch</em></span>'
            f'<span class="bar"><i style="width:{w:.0f}%"></i></span></div>')
    return "".join(out)


def hot_html(data):
    """右下。いちばん伸びたゲームを1つだけ、グラフつきで。"""
    rising = data.get("rising") or []
    days = data.get("days") or []
    if rising:
        r = rising[0]
        base = r.get("base")
        delta = (f'<b>×{(r.get("growth") or 1):.1f}</b>'
                 f'<span>ふだん {base:g}件 → 今日 {r.get("videos", 0)}件</span>'
                 if base is not None else f'<b>{r.get("videos", 0)}件</b>')
        return (f'<span class="eye">{UP}今日いちばん伸びた</span>'
                f'<div class="g">{e(r.get("game"))}</div>'
                f'<div class="delta">{delta}</div>'
                + bars_html(r.get("spark") or [], days))
    sp = (data.get("spread") or [{}])[0]
    return (f'<span class="eye">{UP}多くの配信者が触った</span>'
            f'<div class="g">{e(sp.get("game"))}</div>'
            f'<div class="delta"><b>{sp.get("channels", 0)}</b>'
            f'<span>チャンネルが配信</span></div>'
            + bars_html(sp.get("spark") or [], days))


def theme_css(name):
    """テーマ名から、CSSの変数と書体の指定を作る。"""
    th = THEMES.get(name) or THEMES["dark"]
    tf, txf = FONTS[th["title"]], FONTS[th["text"]]
    fontq = "&family=".join(dict.fromkeys([tf[0], txf[0]]))
    titleweight = tf[2]
    stroke = th.get("stroke") or ""
    # フチ付き。文字の内側にフチが食い込まないよう paint-order で塗り順を変える。
    # これを指定しないと、太いフチが文字を痩せさせて逆に読みにくくなる。
    ol = (f";-webkit-text-stroke:{stroke} var(--strokec);paint-order:stroke fill"
          if stroke else "")
    # 数字は画数が少ないぶんフチが効きすぎる。細めにする。
    num = (f";-webkit-text-stroke:{float(stroke[:-2]) * .6:g}px var(--strokec)"
           ";paint-order:stroke fill" if stroke else "")
    vars_ = ";".join(f"--{k}:{th[k]}" for k in
                     ("ink", "ink2", "ink3", "card", "line", "rail",
                      "accent", "hot", "on", "sum", "strokec"))
    return {"fontq": fontq, "vars": vars_, "titlefont": tf[1], "textfont": txf[1],
            "titleweight": titleweight,
            "bg": th["bg"], "gamestroke": ol, "numstroke": num}


def build(data, theme="dark"):
    t = data.get("totals") or {}
    th = theme_css(theme)
    note = ("YouTubeの配信タイトルを毎日自動で解析しています<br>"
            "Shorts・切り抜きは対象外／同じ配信者が同じ日に出した続きものは1件として集計")
    css = CSS % {"bg": th["bg"], "titlefont": th["titlefont"],
                 "textfont": th["textfont"], "titleweight": th["titleweight"],
                 "gamestroke": th["gamestroke"], "numstroke": th["numstroke"]}
    return PAGE % {
        "css": css, "vars": th["vars"], "fontq": th["fontq"], "crown": CROWN,
        "date": e(str(data.get("date", "")).replace("-", ".")),
        "videos": t.get("videos", 0), "channels": t.get("channels", 0),
        "lead": lead_html(data.get("column"), data.get("ranking") or []),
        "rows": rows_html(data.get("ranking") or []),
        "hot": hot_html(data),
        "note": note, "url": SITE_URL, "fit": FIT,
    }

def main():
    data = read_json(SITE / "data.json", None)
    if not data:
        log("site/data.json がありません。先に build_site.py を動かしてください。")
        return 1
    cfg = read_json(SITE.parent / "data" / "site_config.json", {}) or {}
    theme = cfg.get("card_theme") or "dark"
    out_name = "card"
    for a in sys.argv[1:]:
        if a.startswith("--theme="):
            theme = a.split("=", 1)[1]
        if a.startswith("--out="):
            out_name = a.split("=", 1)[1]
    if theme not in THEMES:
        log(f"そんなテーマはありません: {theme}（{'・'.join(THEMES)}）")
        return 1
    out = SITE / f"{out_name}.html"
    out.write_text(build(data, theme), encoding="utf-8")
    log(f"カードを書き出しました: {out}（テーマ {theme}）")

    if "--png" in sys.argv:
        from playwright.sync_api import sync_playwright
        png = SITE / f"{out_name}.png"
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": 1600, "height": 900},
                            device_scale_factor=1)
            pg.goto("file://" + str(out.resolve()))
            pg.wait_for_timeout(1800)          # フォントの読み込み待ち
            pg.screenshot(path=str(png))
            b.close()
        log(f"画像を書き出しました: {png}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
