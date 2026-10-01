#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""週まとめ・月まとめのコラムから、Xに貼る画像（1600×900）と投稿文を作る。

    python3 scripts/make_week_card.py data/columns/weekly/2026-09-14.json --png
    python3 scripts/make_week_card.py data/columns/monthly/2026-09.json --png

**週と月のどちらでも同じこれを使う**（2026-10-01に月も通した）。
ファイル名で見分ける。`2026-09-14` なら週、`2026-09` なら月。
中身の形も、出す3行も、両方いっしょ。名前は week のままだが、
片方だけ別のプログラムにすると見た目がすぐ食い違うので1本にしてある。

なぜ毎日のカード（make_card.py）と別なのか（2026-09-28 たろちんさん）
--------------------------------------------------------------------
週まとめは400〜700字ある。毎日のコラムと同じ型で作ると、本文が小さくなって
タイムラインでは読めない。たろちんさんの指示:

> 週まとめコラムは文章量が多いので全てをカードにすることはしない。
> 毎日サイトにのせている3行サマリーのようなものでよい。
> メインのトピックスを強調しつつ、スペースがあれば1行程度で説明。
> 下部に「こんなこともありました」として、その他の出来事を2行ほど。

なので**3行しか載せない。**
  見出し … いちばん大きく、色も変える
  その説明 … 50〜100字。何が起きたのかは、ここを読めば分かるようにする
  「こんなこともありました」 … その他の出来事を2行

配信のサムネイルは載せない。毎日のカードは「どの配信の話か」を見せるために
借りているが、こちらに載るのは見出しと、こちらが数えた数字だけ。
借りものが無いぶん、画像の生成がサムネイルの取得に左右されない
（毎日のカードが手元で card_preview.png にしかならない原因がこれ）。

JSONに足す欄
------------
    "card": {
      "sub":  "見出しの中身を説明する文。50〜100字。2〜3行になる",
      "also": ["ほかの出来事（20〜44字）", "もう1つ"]
    }

省いてもよい。sub が無ければ lead の1文目を使い、also が無ければ
「こんなこともありました」の枠ごと出さない（そのぶん見出しが大きくなる）。
この欄はカードと投稿文だけに使う。サイトの本文には出ない。
"""
import argparse
import json
import re
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_site import POINT  # noqa: E402
from common import DATA, log, read_json  # noqa: E402
from make_card import (THEMES, e, font_link, ico, site_url,  # noqa: E402
                       theme_css, x_weight)

FIT_WAIT = 20000      # 文字を詰め終わる合図を待つ上限（ミリ秒）
SUB_MIN, SUB_MAX = 45, 105
#                     見出しの下に置く説明の長さ（字）。目安は50〜100。
#                     1行では足りないので2〜3行使う。短いと札が寂しく、
#                     長いと「こんなこともありました」を押し出す
ALSO_MAX = 44         # 「こんなこともありました」1行の上限（字）。
                      # 画像はもっと入るが、投稿文が280字に収まらなくなる
ALSO_N = 3            # 並べられる行数の上限。投稿文に収まるのはふつう2行まで

BOLT = ico('<path d="M13 2L4 14h7l-1 8 9-12h-7l1-8z"/>')
PLUS = ico('<path d="M12 5v14M5 12h14"/>')

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{width:1600px;height:900px;overflow:hidden;color:var(--ink);background:%(bg)s;
  font-family:%(textfont)s;padding:34px 44px 30px;display:flex;flex-direction:column;gap:20px}

header{display:flex;align-items:center;gap:16px;flex:none}
header img{width:48px;height:48px;object-fit:contain}
header .nm{font-family:%(titlefont)s;font-weight:%(titleweight)s;font-size:28px;color:var(--ink)}
header .tag{font-size:15px;color:var(--ink2);font-weight:700}
header .meta{margin-left:auto;text-align:right}
header .d{font-family:"Roboto Mono",monospace;font-size:27px;font-weight:700;
  color:var(--accent);line-height:1}
header .c{font-size:13px;color:var(--ink2);margin-top:6px;font-weight:700}

/* 札は1枚。3行を「並んだもの」として読ませたいので、
   主役だけ別の箱に入れる作りはやめた（2026-09-28 たろちんさん）。
     「見た目がアンバランス。『週まとめ』の文字は小さすぎるし、
       見出しは異様に大きすぎる。3行サマリーを普通に並べる感じで」
   強弱は大きさと色でつける。箱を分けてはつけない。 */
/* 札は高さいっぱい。ただし中身は space-evenly で散らす。
   下に寄せると真ん中に穴が空き、中身ぶんの高さにすると札が宙に浮く。
   どちらも試して、余りを均等に配ったこの形に落ち着いた。 */
.card{flex:1 1 auto;background:var(--card);border:1px solid var(--line);
  border-radius:20px;padding:30px 40px;display:flex;flex-direction:column;
  justify-content:space-evenly;min-height:0}
/* 「こんなこともありました」が無い日。散らす相手がいないので、
   まとめて真ん中に置く（space-evenly のままだと2つが上下に離れる） */
.card.solo{justify-content:center;gap:30px}
.eye{align-self:flex-start;display:inline-flex;align-items:center;gap:10px;
  font-family:%(titlefont)s;font-weight:%(titleweight)s;font-size:25px;color:var(--on);
  background:var(--hot);padding:10px 22px 10px 17px;border-radius:11px;flex:none}
.eye svg{width:22px;height:22px}

/* 1行目。主役だが、3行の並びから浮かない大きさにとどめる */
.hd{font-family:%(titlefont)s;font-weight:%(titleweight)s;
  font-size:62px;line-height:1.32;letter-spacing:-.01em;color:var(--hot);
  display:flex;gap:18px;align-items:flex-start;flex:0 1 auto;min-height:0;overflow:hidden}
.hd.short{font-size:70px}
.hd.long{font-size:53px}
.hd .pt{flex:none;width:.86em;height:.86em;margin-top:.3em;fill:currentColor}

/* 見出しの説明。見出しの字下げに合わせて、同じ塊に見えるようにする。
   50〜100字を置くので2〜3行になる（2026-09-28 たろちんさん）。
   ここが「何が起きたのか」を受け持つ本文にあたる。 */
.sub{margin-top:16px;padding-left:calc(.86em + 18px);font-size:27px;font-weight:700;
  line-height:1.72;color:var(--ink2);flex:0 1 auto;min-height:0;overflow:hidden}
.lead{flex:0 1 auto;min-height:0;display:flex;flex-direction:column}

/* 残りの2行。主役よりやや小さく、色は地の文のまま。
   上の余白は margin-top:auto が引き受けるので、行数が変わっても下端で揃う */
.also{padding-top:28px;border-top:1px solid var(--line);flex:none}
.also .lbl{font-size:20px;font-weight:900;color:var(--accent);
  display:flex;align-items:center;gap:9px}
.also .lbl svg{width:19px;height:19px}
.also ul{list-style:none;margin-top:16px;display:flex;flex-direction:column;gap:13px}
.also li{font-size:32px;font-weight:700;line-height:1.45;color:var(--sum);
  display:flex;gap:15px;align-items:flex-start}
.also li::before{content:"";flex:none;width:11px;height:11px;margin-top:.55em;
  border-radius:3px;background:var(--accent)}

footer{flex:none;display:flex;align-items:center;gap:20px}
.note{font-size:13px;color:var(--ink3);line-height:1.7;font-weight:700}
.url{margin-left:auto;font-family:"Roboto Mono",monospace;font-size:20px;font-weight:700;
  color:var(--on);background:var(--accent);border-radius:10px;padding:10px 19px;white-space:nowrap}
"""

PAGE = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<link rel="stylesheet" href="%(fontlink)s">
<style>:root{%(vars)s}
%(css)s</style></head><body>
<header>
  <img src="logo.svg" alt="">
  <span class="nm">ハヤリゲー</span>
  <span class="tag">「次に流行るゲーム」がわかるサイト</span>
  <div class="meta"><div class="d">%(range)s</div>
    <div class="c">%(counts)s</div></div>
</header>
<section class="card%(solo)s">
  <span class="eye">%(bolt)s%(label)s</span>
  <div class="lead">
    <div class="hd%(ttsize)s">%(point)s<span>%(title)s</span></div>
    %(sub)s
  </div>
  %(also)s
</section>
<footer>
  <div class="note">%(note)s</div>
  <span class="url">%(url)s</span>
</footer>
<script>%(fit)s</script>
</body></html>
"""

# 見出しは10〜30字と幅がある。字数だけで大きさを決めると、
# 同じ字数でも漢字とカナで行数が変わって、はみ出す日が出る。
# 実際に描いてから1段ずつ縮める（毎日のカードと同じやり方）。
FIT = """
(function(){
  function run(){
    var t=document.querySelector('.hd'), s=document.querySelector('.sub');
    // 札は中身ぶんの高さなので、あふれるとしたら画像（900px）のほう
    function over(){ return document.body.scrollHeight > 901; }
    var sizes=[70,62,56,53,48,44,40,36];
    // いま当たっている大きさより小さいところから始める（大きくはしない）
    var now=parseFloat(getComputedStyle(t).fontSize);
    sizes=sizes.filter(function(s){ return s<=now; });
    for(var i=0;i<sizes.length && over();i++) t.style.fontSize=sizes[i]+'px';
    // それでも入らなければ補足のほうを縮める。1行目は最後まで守る。
    if(s){ var ss=[27,25,23,21,19,18];
      for(var j=0;j<ss.length && over();j++) s.style.fontSize=ss[j]+'px'; }
    window.__fit=true;
  }
  var ready=(document.fonts&&document.fonts.ready)||Promise.resolve();
  var giveup=new Promise(function(r){ setTimeout(r,6000); });
  Promise.race([ready,giveup]).then(run);
})();
"""


def period(key):
    """ファイル名から (始まり, 終わり, 見出しの札, URLの一文字) を返す。

      2026-09-14 … 週まとめ。その月曜から日曜まで
      2026-09    … 月まとめ。その月の1日から末日まで
    """
    if re.fullmatch(r"\d{4}-\d{2}", key):
        a = datetime.strptime(key + "-01", "%Y-%m-%d")
        nxt = datetime(a.year + (a.month == 12), (a.month % 12) + 1, 1)
        return a, nxt - timedelta(days=1), "月まとめ", "m"
    a = datetime.strptime(key, "%Y-%m-%d")
    return a, a + timedelta(days=6), "週まとめ", "w"


def week_counts(a, b):
    """その期間、何日ぶん集計して、配信が何本あったか。
    data/archive_index.json（日ごとの集計結果）から数える。
    取れなければ空文字を返して、header の右下を出さない。"""
    arch = read_json(DATA / "archive_index.json", []) or []
    lo, hi = a.strftime("%Y-%m-%d"), b.strftime("%Y-%m-%d")
    days = [x for x in arch if lo <= str(x.get("date", "")) <= hi]
    if not days:
        return ""
    vids = sum(int(x.get("videos") or 0) for x in days)
    return f"{len(days)}日分を集計 ／ 配信 {vids:,}本"


def first_sentence(text):
    """lead の1文目。sub が書かれていないときの受け皿。"""
    t = re.split(r"(?<=[。！？])", str(text or "").strip())
    return (t[0] if t else "").strip()


def card_parts(col):
    """カードに載せる3行を取り出す。足りないぶんは埋めずに省く。"""
    card = col.get("card") or {}
    sub = str(card.get("sub") or "").strip() or first_sentence(col.get("lead"))
    also = [str(x).strip() for x in (card.get("also") or []) if str(x).strip()]
    return sub, also[:ALSO_N]


def build(col, key, theme="dark"):
    th = theme_css(theme)
    a, b, label, _slug = period(key)
    title = str(col.get("title") or "").strip()
    sub, also = card_parts(col)
    n = len(title)
    css = CSS % {"bg": th["bg"], "titlefont": th["titlefont"],
                 "textfont": th["textfont"], "titleweight": th["titleweight"],
                 "gamestroke": th["gamestroke"]}
    also_html = ""
    if also:
        lis = "".join(f"<li>{e(x)}</li>" for x in also)
        also_html = (f'<div class="also">'
                     f'<div class="lbl">{PLUS}こんなこともありました</div>'
                     f"<ul>{lis}</ul></div>")
    return PAGE % {
        "css": css, "vars": th["vars"], "fontlink": font_link(th["fontq"]),
        "bolt": BOLT,
        "range": (a.strftime("%Y.%m") if label == "月まとめ"
                  else f"{a.strftime('%Y.%m.%d')} – {b.strftime('%m.%d')}"),
        "label": label,
        "counts": e(week_counts(a, b)),
        "title": e(title),
        "point": POINT,
        "solo": "" if also else " solo",
        "ttsize": " long" if n > 24 else (" short" if n <= 15 else ""),
        "sub": f'<div class="sub">{e(sub)}</div>' if sub else "",
        "also": also_html,
        "note": ("YouTubeの配信タイトルを毎日自動で解析しています<br>"
                 "件数・チャンネル数は当サイトが独自に数えたものです"),
        "url": site_url(), "fit": FIT,
    }


# ---------------------------------------------------------------- 投稿文
def tweet_text(col, key):
    """Xに貼る投稿文。毎朝の形（make_card.py の tweet_text）をそろえてある。

        先週の #ハヤリゲー（9/14〜9/20）🎮

        ★犯罪の街で、いちばん見られたのは黒服の夜

        GTA5の街「SURGE Town」が9月20日に最終日。17日間で18チャンネル173本

        こんなこともありました
        ・…
        ・…

        https://hayarige.com/w/2026-09-14/

    ★は投稿文だけに足す（毎日のほうと同じ）。JSONには書かない。
    長くなったときは、削るのは1行説明のほう。見出しと
    「こんなこともありました」は残す（そこが3行サマリーの本体なので）。
    """
    title = str(col.get("title") or "").strip()
    if not title:
        return None
    a, b, label, slug = period(key)
    sub, also = card_parts(col)
    head = title if title.startswith("★") else "★" + title
    url = f"https://{site_url()}/{slug}/{key}/"
    if label == "月まとめ":
        top = f"{a.month}月の #ハヤリゲー まとめ🎮\n\n{head}"
    else:
        span = f"{a.month}/{a.day}〜{b.month}/{b.day}"
        top = f"先週の #ハヤリゲー（{span}）🎮\n\n{head}"
    tail = ""
    if also:
        tail = "\n\nこんなこともありました\n" + "\n".join("・" + x for x in also)
    full = f"{top}\n\n{sub}{tail}\n\n{url}" if sub else f"{top}{tail}\n\n{url}"
    if sub and x_weight(full) > 280:
        # 説明を落とす。50〜100字あるので、たいていここで落ちる。
        # 画像には載っているので、投稿から消えても読める
        full = f"{top}{tail}\n\n{url}"
        log("投稿文に入りきらないので、説明は画像だけに載せました。")
    return full


def main():
    ap = argparse.ArgumentParser(description="週・月まとめのカードと投稿文を作る")
    ap.add_argument("column",
                    help="data/columns/weekly/YYYY-MM-DD.json または "
                         "data/columns/monthly/YYYY-MM.json")
    ap.add_argument("--png", action="store_true", help="画像まで作る")
    ap.add_argument("--theme", default="", help="見た目（既定は site_config.json）")
    ap.add_argument("-o", "--out", default="", help="書き出し先のフォルダ")
    args = ap.parse_args()

    p = Path(args.column)
    col = read_json(p, None)
    if not isinstance(col, dict) or not str(col.get("title") or "").strip():
        log(f"週まとめのJSONが読めません（title がありません）: {p}")
        return 1
    key = p.stem
    try:
        period(key)
    except ValueError:
        log("ファイル名が「その週の月曜の日付」（2026-09-14）か"
            f"「その月」（2026-09）になっていません: {p.name}")
        return 1

    theme = args.theme or (read_json(DATA / "site_config.json", {}) or {}
                           ).get("card_theme") or "dark"
    if theme not in THEMES:
        log(f"そんなテーマはありません: {theme}（{'・'.join(THEMES)}）")
        return 1

    out = Path(args.out) if args.out else Path(tempfile.gettempdir())
    out.mkdir(parents=True, exist_ok=True)
    # ロゴは画像の中に出るので、書き出し先に一緒に置く
    logo = Path(__file__).resolve().parent.parent / "site" / "logo.svg"
    if logo.is_file():
        (out / "logo.svg").write_bytes(logo.read_bytes())

    kind = period(key)[2]
    html_path = out / f"{'month' if kind == '月まとめ' else 'week'}-card-{key}.html"
    html_path.write_text(build(col, key, theme), encoding="utf-8")
    log(f"カードのHTMLを書きました: {html_path}（見た目 {theme}）")

    sub, also = card_parts(col)
    log(f"見出し: {col.get('title')}（{len(str(col.get('title') or ''))}字）")
    log(f"説明: {sub}（{len(sub)}字）")
    if len(sub) > SUB_MAX:
        log(f"⚠️ 説明が長すぎます（目安は50〜100字、{SUB_MAX}字まで）。"
            "下の2行が押し出されます")
    elif len(sub) < SUB_MIN:
        log(f"※ 説明が短めです（目安は50〜100字）。"
            "何が起きたのかがここだけで分かる長さにしてください")
    if not also:
        log("こんなこともありました: なし（card.also が空です）")
    for x in also:
        log(f"  ・{x}（{len(x)}字）")
        if len(x) > ALSO_MAX:
            log(f"    ⚠️ 長すぎます（{ALSO_MAX}字まで）")

    text = tweet_text(col, key)
    tw = out / f"{'month' if kind == '月まとめ' else 'week'}-tweet-{key}.txt"
    tw.write_text(text + "\n", encoding="utf-8")
    n = x_weight(text)
    log(f"投稿文を書きました: {tw}（約{n}文字ぶん／上限280）")
    if n > 280:
        # どれだけ削ればよいかまで出す。「超えています」だけだと、
        # 何字詰めればいいのかが分からず、何度も作り直すことになる。
        # 日本語は1字で2文字ぶん数えるので、超過の半分が削る字数の目安。
        over = n - 280
        log(f"⚠️ Xの上限を {over} 文字ぶん超えています（約{-(-over // 2)}字）。"
            "見出しを短くするか、「こんなこともありました」の2行を詰めてください。")
        log("   見出しにゲーム名を入れると長くなります。"
            "そのぶん『こんなこともありました』は1行30字くらいに抑えると収まります。")
    log("---- ここから投稿文 ----")
    log(text)
    log("---- ここまで ----")

    if args.png:
        from playwright.sync_api import sync_playwright
        png = out / f"{'month' if kind == '月まとめ' else 'week'}-card-{key}.png"
        with sync_playwright() as p2:
            b = p2.chromium.launch()
            pg = b.new_page(viewport={"width": 1600, "height": 900},
                            device_scale_factor=1)
            pg.goto("file://" + str(html_path.resolve()))
            try:
                pg.wait_for_function("window.__fit === true", timeout=FIT_WAIT)
            except Exception:
                log("文字の大きさを詰める処理が終わりませんでした。そのまま撮ります。")
            pg.wait_for_timeout(300)
            # 書体が当たっているかだけ確かめる。このカードは配信のサムネイルを
            # 使わないので、確かめるところはここだけで済む。
            loaded = pg.evaluate("""() => [...document.fonts]
                .filter(f => f.status === 'loaded').map(f => f.family)""")
            miss = [f for f in (q.split(":")[0].replace("+", " ")
                                for q in theme_css(theme)["fontq"].split("&family="))
                    if f not in loaded]
            pg.screenshot(path=str(png))
            b.close()
        if miss:
            log("⚠️ 書体が当たっていません: " + "・".join(miss))
            log("   この画像は見本と違う書体で出ます。投稿前に見て確かめてください。")
        log(f"画像を書きました: {png}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
