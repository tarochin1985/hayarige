#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""XやDiscordにURLを貼ったときに出るカード用の画像（1200×630）を作る。

    python scripts/make_ogp.py

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

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{width:1200px;height:630px;overflow:hidden;color:#E9F1F0;
  background:radial-gradient(780px 720px at 100% 52%,#14484B 0%,rgba(20,72,75,0) 66%),
             radial-gradient(620px 470px at -6% 112%,#33200F 0%,rgba(51,32,15,0) 60%),#091012;
  font-family:"Zen Kaku Gothic New","Noto Sans JP",sans-serif;
  padding:56px 64px;display:grid;grid-template-columns:1fr 400px;align-items:center;gap:24px}
/* 右半分が真っ黒だと、貼られたときに「作りかけ」に見える。
   ロゴを大きく置いて画面を使い切る。数字は入れない（Xは画像をURL単位で
   キャッシュするので、日が経つと古い数字を出し続けることになる）。 */
.mark{grid-column:2;justify-self:center;width:352px;height:352px;object-fit:contain;
  filter:drop-shadow(0 26px 64px rgba(0,0,0,.55))}
.L{grid-column:1;display:flex;flex-direction:column;justify-content:center}
.brand{display:flex;align-items:center;gap:13px;font-size:28px;font-weight:900;color:#8FE4E7}
.brand i{display:block;width:28px;height:3px;background:#E8975C;border-radius:2px}
h1{font-size:70px;font-weight:900;line-height:1.16;margin-top:18px;letter-spacing:-.01em}
h1 em{font-style:normal;color:#6FDCE0}
.sub{margin-top:22px;font-size:23px;font-weight:500;color:#A6C2C3;line-height:1.65}
.url{align-self:flex-start;margin-top:30px;font-family:"Roboto Mono",monospace;font-size:22px;
  font-weight:700;color:#0A1113;background:#6FDCE0;border-radius:10px;padding:12px 20px;white-space:nowrap}
.chips{display:flex;gap:9px;margin-top:16px}
.chips span{font-size:16px;color:#9FBCBD;border:1px solid #2A4245;border-radius:20px;padding:6px 15px}
"""

PAGE = """<!doctype html><html lang="ja"><head><meta charset="utf-8">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Zen+Kaku+Gothic+New:wght@500;900&family=Noto+Sans+JP:wght@500;900&family=Roboto+Mono:wght@700&display=swap">
<style>%(css)s</style></head><body>
  <div class="L">
    <div class="brand"><i></i>ハヤリゲー</div>
    <h1>次、<em>何のゲーム</em><br>配信する？</h1>
    <div class="sub">VTuber・ゲーム実況者が、いま配信しているゲーム。<br>YouTubeの配信タイトルを毎日自動で集計。</div>
    <span class="url">%(url)s</span>
    <div class="chips"><span>毎日更新</span><span>登録不要</span><span>無料</span></div>
  </div>
  <img class="mark" src="logo.svg" alt="">
</body></html>
"""


def main():
    url = "hayarige.tarochin1985.workers.dev"
    for a in sys.argv[1:]:
        if a.startswith("--url="):
            url = a.split("=", 1)[1]
    html = SITE / "_ogp.html"
    html.write_text(PAGE % {"css": CSS, "url": url}, encoding="utf-8")
    from playwright.sync_api import sync_playwright
    out = SITE / "ogp.png"
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1200, "height": 630}, device_scale_factor=1)
        pg.goto("file://" + str(html.resolve()))
        pg.wait_for_timeout(1500)          # フォントの読み込み待ち
        pg.screenshot(path=str(out))
        b.close()
    html.unlink()
    log(f"OGP画像を書き出しました: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
