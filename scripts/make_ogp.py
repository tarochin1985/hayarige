#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""XやDiscordにURLを貼ったときに出るカード用の画像（1200×630）を作る。

    python scripts/make_ogp.py                 … 既定のテーマで1枚
    python scripts/make_ogp.py --theme=white   … テーマを選ぶ
    python scripts/make_ogp.py --all           … 全テーマを見本として書き出す

毎日の更新では作り直さない。理由は2つ。
  1. Xは画像をURL単位でキャッシュするので、中身を毎日変えても
     貼られた時期によって古い画像が出る。かえって分かりにくい。
  2. ランキングの数字を入れると、拡散されたリンクが何日も前の数字を
     出し続けることになる。その日の数字は card.png のほうで出す。
なので、ここは「サイトが何であるか」だけを書いた、変わらない1枚にしてある。
ロゴやキャッチコピーを変えたときだけ動かせばよい。
"""
import sys
from pathlib import Path
from common import SITE, log

# 配色。1枚だけの画像なので、ここを選ぶだけで雰囲気が変わるようにしてある。
# Xのタイムラインでは小さく出るので、背景と文字の明るさの差をしっかり取る。
# （2026-09-21 「黒背景にグレーの文字だと埋もれる」という指摘を受けて作った）
THEMES = {
    # 毎日のツイート画像と同じ配色。サイト全体で見た目をそろえたいならこれ。
    "cream": {
        "bg": ("radial-gradient(1100px 760px at 78% -18%,#FFE7CE 0%,rgba(255,231,206,0) 62%),"
               "radial-gradient(760px 560px at -6% 112%,#D9F0EE 0%,rgba(217,240,238,0) 58%),#FBF7F1"),
        "ink": "#172123", "sub": "#4A6265", "brand": "#0B6B70", "em": "#0B6B70",
        "bar": "#D2590C", "chip": "#4F6567", "chipline": "#DCD3C6",
        "urlbg": "#0B6B70", "urlink": "#FFFFFF", "shadow": ".20",
    },
    # まっさらな白。いちばん文字が読みやすく、どんな背景のタイムラインでも浮く。
    "white": {
        "bg": "#FFFFFF",
        "ink": "#111B1D", "sub": "#48605F", "brand": "#0B6B70", "em": "#0B6B70",
        "bar": "#B4551C", "chip": "#5E7577", "chipline": "#DBE4E2",
        "urlbg": "#0B6B70", "urlink": "#FFFFFF", "shadow": ".14",
    },
    # サイトの背景と同じ、ほんのり緑がかった白。白より少し落ち着く。
    "paper": {
        "bg": ("radial-gradient(900px 700px at 88% -12%,#E4F1EF 0%,rgba(228,241,239,0) 64%),"
               "#F3F5F4"),
        "ink": "#111B1D", "sub": "#465D5F", "brand": "#0B6B70", "em": "#0B6B70",
        "bar": "#B4551C", "chip": "#5A7072", "chipline": "#D3DEDC",
        "urlbg": "#111B1D", "urlink": "#FFFFFF", "shadow": ".16",
    },
    # ブランド色をそのまま背景に。小さく出たときにいちばん目立つ。
    "teal": {
        "bg": ("radial-gradient(900px 760px at 92% 10%,#0E8B90 0%,rgba(14,139,144,0) 64%),"
               "#0B5F63"),
        "ink": "#FFFFFF", "sub": "#CDE9E8", "brand": "#FFFFFF", "em": "#FFD9A8",
        "bar": "#FFB870", "chip": "#BFE2E1", "chipline": "#3A8488",
        "urlbg": "#FFFFFF", "urlink": "#0B5F63", "shadow": ".30",
    },
    # もとの暗い配色。文字の明るさを上げて埋もれないようにしてある。
    "dark": {
        "bg": ("radial-gradient(780px 720px at 100% 52%,#14484B 0%,rgba(20,72,75,0) 66%),"
               "radial-gradient(620px 470px at -6% 112%,#33200F 0%,rgba(51,32,15,0) 60%),#091012"),
        "ink": "#FFFFFF", "sub": "#CBE0E0", "brand": "#8FE4E7", "em": "#6FDCE0",
        "bar": "#E8975C", "chip": "#BBD3D4", "chipline": "#31494C",
        "urlbg": "#6FDCE0", "urlink": "#08191B", "shadow": ".55",
    },
}
DEFAULT_THEME = "cream"

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{width:1200px;height:630px;overflow:hidden;color:%(ink)s;background:%(bg)s;
  font-family:"Zen Kaku Gothic New","Noto Sans JP",sans-serif;
  padding:52px 62px;display:grid;grid-template-columns:1fr 380px;align-items:center;gap:20px}
/* 右半分が空だと「作りかけ」に見える。ロゴを大きく置いて画面を使い切る。
   数字は入れない（Xは画像をURL単位でキャッシュするので、日が経つと
   古い数字を出し続けることになる）。 */
.mark{grid-column:2;justify-self:center;width:330px;height:330px;object-fit:contain;
  filter:drop-shadow(0 22px 56px rgba(0,0,0,%(shadow)s))}
.L{grid-column:1;display:flex;flex-direction:column;justify-content:center}
/* サイトの名前。ここが小さいと何のサイトか残らないので、大きく出す。 */
.brand{display:flex;align-items:center;gap:15px;font-size:46px;font-weight:900;
  color:%(brand)s;letter-spacing:.01em;line-height:1}
.brand i{display:block;width:40px;height:5px;background:%(bar)s;border-radius:3px;flex:none}
h1{font-size:57px;font-weight:900;line-height:1.24;margin-top:20px;letter-spacing:-.02em;
  white-space:nowrap}
h1 em{font-style:normal;color:%(em)s}
.sub{margin-top:18px;font-size:21px;font-weight:500;color:%(sub)s;line-height:1.6;
  white-space:nowrap}
.url{align-self:flex-start;margin-top:26px;font-family:"Roboto Mono",monospace;font-size:22px;
  font-weight:700;color:%(urlink)s;background:%(urlbg)s;border-radius:10px;padding:11px 19px;
  white-space:nowrap}
.chips{display:flex;gap:9px;margin-top:14px}
.chips span{font-size:16px;color:%(chip)s;border:1px solid %(chipline)s;border-radius:20px;
  padding:5px 14px}
"""
PAGE = """<!doctype html><html lang="ja"><head><meta charset="utf-8">
<link rel="stylesheet" href="%(fontlink)s">
<style>%(css)s</style></head><body>
  <div class="L">
    <div class="brand"><i></i>ハヤリゲー</div>
    <h1><em>「次に流行るゲーム」</em><br>がわかるサイト</h1>
    <div class="sub">VTuber・ゲーム実況者のYouTube配信を、毎日数えています。<br>いま配信が増えているゲームがわかります。</div>
    <span class="url">%(url)s</span>
    <div class="chips"><span>毎日更新</span><span>登録不要</span><span>無料</span></div>
  </div>
  <img class="mark" src="logo.svg" alt="">
</body></html>
"""


def render(theme, url, fontlink, out, pg):
    css = CSS % dict(THEMES[theme], bg=THEMES[theme]["bg"])
    html = SITE / f"_ogp_{theme}.html"
    html.write_text(PAGE % {"css": css, "url": url, "fontlink": fontlink},
                    encoding="utf-8")
    pg.goto("file://" + str(html.resolve()))
    pg.wait_for_timeout(1200)              # 書体の読み込み待ち
    pg.screenshot(path=str(out))
    html.unlink()
    log(f"OGP画像を書き出しました: {out}（テーマ {theme}）")


def main():
    from common import DATA, read_json
    cfg = read_json(DATA / "site_config.json", {}) or {}
    url = str(cfg.get("site_url") or "")
    url = url.replace("https://", "").replace("http://", "").rstrip("/") or "hayarige.com"
    theme = str(cfg.get("ogp_theme") or DEFAULT_THEME)
    every = False
    for a in sys.argv[1:]:
        if a.startswith("--url="):
            url = a.split("=", 1)[1]
        elif a.startswith("--theme="):
            theme = a.split("=", 1)[1]
        elif a == "--all":
            every = True
    if theme not in THEMES:
        log(f"テーマ「{theme}」はありません。{' / '.join(THEMES)} のどれかにしてください。")
        return 2

    # 書体はカード画像と同じ仕組みで解決する。Google Fontsが届かない環境でも
    # 同じ書体で出るように、make_card.py の仕掛けを使い回す。
    from make_card import font_link
    fonts = ("Zen+Kaku+Gothic+New:wght@500;900&family=Noto+Sans+JP:wght@500;900"
             "&family=Roboto+Mono:wght@700")
    link = font_link(fonts)

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1200, "height": 630}, device_scale_factor=1)
        if every:
            for t in THEMES:
                render(t, url, link, SITE / f"ogp_{t}.png", pg)
        else:
            render(theme, url, link, SITE / "ogp.png", pg)
        b.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
