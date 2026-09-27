#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""書いたコラムを、**本番と同じ見た目**で1枚のHTMLにして出す。

    python3 scripts/preview_column.py data/columns/2026-09-27.json
    python3 scripts/preview_column.py data/columns/2026-09-27.json -o /tmp/p.html

なぜ作ったか（2026-09-27 たろちんさん）
--------------------------------------
朝の定期実行では、コラムのJSONと一緒に「確認用のHTML」を手で書いて渡していた。
見出し・本文・出典が読めればよい、という作りだった。

そこに「今日の見どころ」（notes）が加わって足りなくなった。notes は
**急上昇のカードの上に並ぶ短い補足**で、カードに出ている数字と並べて読んだとき
どう見えるかが大事なところ。手書きのプレビューではそれが分からない。

このプログラムは site/data.json（前回の書き出しの結果）にコラムを差し込んで、
site/template.html ＝ **本番とまったく同じ型紙**でトップページを1枚組み立てる。
だから「見どころ」がカードの上にどう並ぶか、行が長すぎないか、そのまま見える。

site/ の中には何も書かない。GitHubには絶対に上がらない。

注意
----
カード（急上昇）の中身は site/data.json のもの、つまり **前回の更新のとき**の
ものになる。今日ぶんの更新が回っていなければ、前の日の急上昇が出る。
コラムの日付と data.json の日付が違うときは警告を出す。
"""
import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_site import enrich_column, page_html  # noqa: E402
from common import DATA, SITE, log, read_json  # noqa: E402

# プレビューだと一目で分かる帯。本番と見間違えると、まだ上げていないものを
# 「もう出ている」と思ってしまう。
BANNER = """
<div style="position:fixed;left:0;right:0;bottom:0;z-index:9999;
  background:#B4551C;color:#fff;font:600 13px/1.5 system-ui,sans-serif;
  padding:9px 14px;text-align:center;
  box-shadow:0 -2px 12px rgba(0,0,0,.18)">
  これは確認用のプレビューです（__DAY__ のコラム）。
  まだサイトには出ていません。カードの中身は前回の更新のときのものです。
</div>
<div style="height:44px"></div>
"""


def main():
    ap = argparse.ArgumentParser(
        description="コラムを本番と同じ見た目で1枚のHTMLにする")
    ap.add_argument("column", help="data/columns/YYYY-MM-DD.json")
    ap.add_argument("-o", "--out", default="",
                    help="書き出し先。既定は一時フォルダ")
    a = ap.parse_args()

    cpath = Path(a.column)
    col = read_json(cpath, None)
    if not isinstance(col, dict):
        log(f"コラムのJSONが読めませんでした: {cpath}")
        return 1
    # ファイル名が日付なので、date が書かれていなくても補える
    day = str(col.get("date") or cpath.stem)
    col.setdefault("date", day)

    data = read_json(SITE / "data.json", None)
    if not isinstance(data, dict):
        log("site/data.json がありません。先に python3 scripts/build_site.py "
            "を回してください")
        return 1

    if str(data.get("date") or "") != day:
        log(f"⚠️ コラムは {day} ですが、site/data.json は "
            f"{data.get('date')} のものです。"
            "カード（急上昇）はそちらの日のものが出ます")

    rows = data.get("ranking") or []
    if not any(r.get("game") == col.get("game") for r in rows):
        log(f"ℹ️ 『{col.get('game')}』は data.json の順位表（上位30）に"
            "ありません。見出しの画像は出典の動画から作ります")

    enrich_column(col, rows)
    d = dict(data, column=col)
    # プレビューは1枚もの。画像・書体・リンクは本番の住所から取りに行く
    site_url = (read_json(DATA / "site_config.json", {}) or {}).get(
        "site_url") or "https://hayarige.com"
    site_url = site_url.rstrip("/")
    html = page_html("index.html", d, 0, site_url, home=site_url + "/")
    html = html.replace("</body>", BANNER.replace("__DAY__", day) + "</body>")

    out = Path(a.out) if a.out else Path(tempfile.gettempdir()) / \
        f"hayarige-preview-{day}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")

    ns = [str(x).strip() for x in (col.get("notes") or []) if str(x).strip()]
    log(f"プレビューを書きました: {out}")
    log(f"見出し: {col.get('headline')}")
    log(f"本文: {len(str(col.get('body') or ''))}字")
    if ns:
        log(f"今日の見どころ: {len(ns)}行")
        for n in ns:
            log(f"  ・{n}（{len(n)}字）")
    else:
        log("今日の見どころ: なし（notes が空です）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
