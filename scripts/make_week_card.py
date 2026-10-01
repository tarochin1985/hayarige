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
      "also": ["ほかの出来事（20〜44字）", "もう1つ"]   ← 週まとめ
      "best": [{"g": "1位のゲーム名", "n": "ひとこと"},  ← 月まとめ
               {"g": "2位", "n": "…"}, {"g": "3位", "n": "…"}]
    }

省いてもよい。sub が無ければ lead の1文目を使い、also が無ければ
「こんなこともありました」の枠ごと出さない（そのぶん見出しが大きくなる）。
この欄はカードと投稿文だけに使う。サイトの本文には出ない。

月まとめだけ、札の形が違う（2026-10-01 たろちんさん）
----------------------------------------------------
> 月まとめのツイート用カードは週まとめと少し作り方を変えて
> 「今月のハヤリゲーベスト3」とかにしたらどうだろう。1位は大きめに表示、
> コラムの見出しと要約もそのまま使いつつ、今の「こんなこともありました」の
> ポジションに2位と3位を配置する。

月まとめは**今月伸びたゲーム3本**が記事の骨で、見出しも要約もその1位の話に
なっている。だから札も順位表の形にする。週まとめは「出来事」を書くもので
順位が無いので、こちらは今までの3行の形のまま（軸が違うから形も違う）。

    1位 … ゲーム名を大きく＋コラムの見出し＋要約（sub）
    2位 3位 … 「こんなこともありました」があった場所に、横並びで

`card.best` が無ければ `sections` の小見出し（「1位 ◯◯」）から名前を拾う。
それも無ければ週まとめと同じ形で出る（落ちはしない）。
"""
import argparse
import json
import re
import sys
import tempfile
import unicodedata
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
                      # ここを超えると画像のほうで2行に折り返す。
                      # ※ 投稿文に2行とも載るかどうかは別で、見出しの長さ次第。
                      #   入らないぶんは tweet_text が後ろから落として、
                      #   「何字詰めれば両方載るか」を画面に出す（2026-10-01）
ALSO_N = 3            # 並べられる行数の上限。投稿文に収まるのはふつう2行まで
BEST_NOTE_MAX = 30    # 月まとめの2位・3位につけるひとことの上限（字）。
                      # 2つ横並びなので、長いと2行になって札の下がつまる
BEST_LABEL = "今月のハヤリゲー ベスト3"
CTA = "👇詳しくはサイトで"
#   投稿文でURLの前に置く1行（2026-10-01 たろちんさん）。週も月も同じ。
#   まとめは400〜700字あって、カードに載るのはそのうちの3行だけ。
#   URLだけ貼っても「続きがある」と伝わらないので、ここで誘導する。

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

/* 1行目。主役だが、3行の並びから浮かない大きさにとどめる。
   書体の決まり（2026-10-01 たろちんさん）
   -----------------------------------------
   見出しに見出し用の書体（Dela Gothic One）を当てていたせいで、
   週まとめのカードだけ毎日のカードと字が違って見えていた。3枚でそろえる。

     見出し用の書体（Dela Gothic One）… **名前に使う。** サイト名・札・ゲーム名だけ
     本文用の書体（丸ゴシック）        … **文に使う。** 見出し900／説明700／一覧800

   毎日のカード（make_card.py）が前からこの分け方で、見出しは丸ゴシックの900。
   こちらだけ Dela だった。分け方のほうを毎日のカードに合わせた。 */
.hd{font-weight:900;
  font-size:62px;line-height:1.32;letter-spacing:-.02em;color:var(--hot);
  display:flex;gap:18px;align-items:flex-start;flex:0 1 auto;min-height:0;overflow:hidden}
.hd.short{font-size:70px}
.hd.long{font-size:53px}
.hd .pt{flex:none;width:.86em;height:.86em;margin-top:.3em;fill:currentColor}

/* 見出しの説明。見出しの字下げに合わせて、同じ塊に見えるようにする。
   50〜100字を置くので2〜3行になる（2026-09-28 たろちんさん）。
   ここが「何が起きたのか」を受け持つ本文にあたる。 */
.sub{margin-top:16px;padding-left:calc(.86em + 18px);font-size:27px;font-weight:700;
  line-height:1.72;color:var(--ink2);flex:0 1 auto;min-height:0;overflow:hidden}
.lead{flex:0 1 auto;min-height:0;min-width:0;display:flex;flex-direction:column}

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

/* ───────── ここから月まとめだけ（2026-10-01 たろちんさん） ─────────
   札を順位表にする。1位はゲーム名を大きく出し、その下にコラムの見出しと
   要約を置く。2位・3位は「こんなこともありました」があった場所へ横並び。
   `.card.best` は `.card.solo` より後に書く。どちらも2クラスぶんの強さなので、
   順番だけが勝ち負けを決める（入れ替えると真ん中寄せに戻って崩れる）。 */
.card.best{justify-content:space-between;gap:20px}
.card.best.solo{justify-content:center;gap:26px}   /* 2位・3位が無いとき */
.one{display:flex;gap:22px;align-items:flex-start;min-width:0;
  flex:0 1 auto;min-height:0;overflow:hidden}

/* 順位の札。1位は塗り、2位・3位は線。
   「1位」と書かずに数字だけにしてある。隣に「ベスト3」と出ているので、
   位の字を3回くり返すと、そのぶんゲーム名に回せる幅が減る。 */
.rk{flex:none;display:flex;align-items:center;justify-content:center;
  font-family:%(titlefont)s;font-weight:%(titleweight)s;line-height:1;
  width:80px;height:80px;border-radius:23px;font-size:45px;margin-top:4px;
  background:var(--hot);color:var(--on)}
.rk.sm{width:50px;height:50px;border-radius:15px;font-size:27px;margin-top:2px;
  background:transparent;color:var(--accent);box-shadow:inset 0 0 0 3px var(--accent)}

/* 1位のゲーム名。『エースコンバット8 ウイングス・オブ・シーヴ』のような
   長い名前があるので、2行まで折り返して、はみ出したら末尾を…にする。
   overflow-wrap:anywhere が無いと、横並びの升目を外へ押し広げる
   （毎日のカードで起きたのと同じこと。2026-09-29） */
.g1{font-family:%(titlefont)s;font-weight:%(titleweight)s;font-size:74px;
  line-height:1.16;letter-spacing:-.01em;color:var(--hot)%(gamestroke)s;
  min-width:0;overflow-wrap:anywhere;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
/* 長い名前は最初から小さく始める。下の FIT は「画像からはみ出したら」しか
   縮めないので、2行で収まってしまう名前には効かない。それだと
   『エースコンバット8 ウイングス・オブ・シーヴ』が2行目に「ーヴ」だけ
   こぼれる形で確定してしまう。1行に入る大きさを先に当てておく。 */
.g1.long{font-size:62px}
.g1.xlong{font-size:52px}
.g1.xxlong{font-size:44px}

/* コラムの見出し。1位のゲーム名の下に来るので、ここでは主役を譲る。
   色は accent にして、ゲーム名（hot）と要約（ink2）の間をつなぐ。 */
.best .hd{margin-top:16px;font-size:39px;line-height:1.38;color:var(--accent);gap:14px}

/* 幅を切っている理由。札の中は1400pxあって、そのまま流すと1行が90字を超える。
   行の終わりから次の行の頭まで目が戻れなくなって、ぱっと読めない。
   1行45字くらいで折り返すと3行になり、空いていた下の余白もここが埋める。 */
.best .hd span{max-width:1200px}
.best .sub{margin-top:15px;padding-left:0;font-size:28px;line-height:1.66;
  max-width:1040px}

.b23{flex:none;padding-top:24px;border-top:1px solid var(--line);
  display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:28px}
.b23 .it{display:flex;gap:16px;align-items:flex-start;min-width:0}
.b23 .tx{min-width:0}
/* ゲーム名だが、毎日のカードの「ほかに伸びたゲーム」と同じ扱いにする
   （あちらも丸ゴシックの800）。Dela は1位のためにとっておく */
.b23 .nm{font-weight:800;font-size:34px;
  line-height:1.22;color:var(--ink);min-width:0;overflow-wrap:anywhere;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.b23 .nt{margin-top:10px;font-size:22px;font-weight:700;line-height:1.5;color:var(--ink2)}

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
%(card)s
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
#
# 縮める順番は週と月で違う（STEPS_WEEK / STEPS_MONTH）。
# 先に書いたものから縮むので、**最後に書いたものがいちばん守られる。**
#   週 … 見出し → 要約。守るのは見出し（それが3行サマリーの1行目）
#   月 … 要約 → 2位3位の名前 → 見出し → 1位の名前。守るのは1位の名前
#        （「ベスト3」の札で、いちばん大きく出すと決めたところなので）
FIT = """
(function(){
  var steps=%(steps)s;
  function run(){
    // 札は中身ぶんの高さなので、あふれるとしたら画像（900px）のほう
    function over(){ return document.body.scrollHeight > 901; }
    steps.forEach(function(st){
      var els=[].slice.call(document.querySelectorAll(st[0]));
      if(!els.length || !over()) return;
      // いま当たっている大きさより小さいところから始める（大きくはしない）
      var now=parseFloat(getComputedStyle(els[0]).fontSize);
      var sizes=st[1].filter(function(v){ return v<=now; });
      for(var i=0;i<sizes.length && over();i++)
        els.forEach(function(el){ el.style.fontSize=sizes[i]+'px'; });
    });
    window.__fit=true;
  }
  var ready=(document.fonts&&document.fonts.ready)||Promise.resolve();
  var giveup=new Promise(function(r){ setTimeout(r,6000); });
  Promise.race([ready,giveup]).then(run);
})();
"""

STEPS_WEEK = [[".hd", [70, 62, 56, 53, 48, 44, 40, 36]],
              [".sub", [27, 25, 23, 21, 19, 18]]]
STEPS_MONTH = [[".sub", [28, 26, 24, 22, 20, 18]],
               [".b23 .nm", [34, 31, 28, 25, 23]],
               [".best .hd", [39, 35, 32, 29, 26, 24]],
               [".g1", [74, 66, 59, 53, 47, 42, 38]]]


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


# ------------------------------------------------- 月まとめの1位〜3位
RANK_H = re.compile(r"^\s*([1-3１-３])\s*位[\s　:：]*(.+?)\s*$")


def best_parts(col):
    """月まとめの1位〜3位を [(名前, ひとこと), …] で返す。無ければ空。

    まず `card.best` を見る。書き方は次のどちらでもよい。
        "best": ["トルネコの大冒険", "鬼武者 Way of the Sword", "モンスト"]
        "best": [{"g": "トルネコの大冒険", "n": "9月30日に22人"}, …]

    書き忘れたときは `sections` の小見出し（「1位 ◯◯」）から名前を拾う。
    こちらが**必ず先に書かれている**ので、`card.best` は名前を短く言い換えたい
    ときと、2位・3位にひとことを足したいときだけ書けばよい。
    1位の "n" は使わない（1位の説明は見出しと要約が受け持つ）。
    """
    out = []
    for x in (col.get("card") or {}).get("best") or []:
        if isinstance(x, dict):
            g, n = str(x.get("g") or "").strip(), str(x.get("n") or "").strip()
        else:
            g, n = str(x or "").strip(), ""
        if g:
            out.append((g, n))
    if out:
        return out[:3]
    # 受け皿。小見出しから。順位の数字どおりに並べる（書いた順に頼らない）
    found = {}
    for sec in col.get("sections") or []:
        m = RANK_H.match(str(sec.get("h") or ""))
        if m:
            found.setdefault(unicodedata.normalize("NFKC", m.group(1)),
                             m.group(2))
    return [(found[k], "") for k in ("1", "2", "3") if k in found]


def _flat(s):
    """名前くらべ用。記号と空白と長音を落として小文字にそろえる。"""
    s = unicodedata.normalize("NFKC", str(s or "")).lower()
    return re.sub(r"[\s・:：;,.。、\-ー–—~〜'’\"“”!?！？/|()\[\]]", "", s)


def strip_lead_name(title, name):
    """見出しの頭の『ゲーム名』を落とす。

    まとめのタイトルは冒頭にゲーム名を入れる決まり（README_まとめ.txt）。
    ところが「ベスト3」の札では、その名前を1位としてすぐ上に大きく出す。
    そのままだと同じ名前が2回並ぶので、札の中だけ頭の『…』を外す。
    毎日のカードの見出しにゲーム名を入れないのと、理由はまったく同じ。

    名前が一致しないときは何もしない（別のゲームの名前かもしれないので）。
    """
    m = re.match(r"^[『「【《]([^』」】》]+)[』」】》]\s*", str(title or ""))
    if not m:
        return title
    a, b = _flat(m.group(1)), _flat(name)
    if a and b and (a in b or b in a):
        return title[m.end():].lstrip("、。・　 ") or title
    return title


def width(s):
    """だいたいの横幅を「全角いくつぶん」で返す。
    `Way of the Sword` のような欧文は、字数ほどには幅を食わない。
    字数だけで大きさを決めると、欧文の名前が必要以上に小さくなる。"""
    return sum(0.55 if ord(c) < 0x1100 else 1.0 for c in str(s or ""))


def g1_class(name):
    """1位のゲーム名を、1行に収まる大きさから始める。
    入る幅は全角で約18字ぶん（74px のとき）。そこから逆算している。"""
    w = width(name)
    for lim, cls in ((18, ""), (21, " long"), (25, " xlong")):
        if w <= lim:
            return cls
    return " xxlong"


def best_html(col, title, sub):
    """月まとめの札の中身。1位が取れなければ None（週と同じ形に戻る）。"""
    best = best_parts(col)
    if not best:
        return None
    g1, _ = best[0]
    hd = strip_lead_name(title, g1)
    rest = ""
    if len(best) > 1:
        its = "".join(
            f'<div class="it"><span class="rk sm">{i}</span><div class="tx">'
            f'<div class="nm">{e(g)}</div>'
            + (f'<div class="nt">{e(n)}</div>' if n else "")
            + "</div></div>"
            for i, (g, n) in enumerate(best[1:], start=2))
        rest = f'<div class="b23">{its}</div>'
    return (f'<section class="card best{"" if rest else " solo"}">'
            f'<span class="eye">{BOLT}{e(BEST_LABEL)}</span>'
            f'<div class="one"><span class="rk">1</span><div class="lead">'
            f'<div class="g1{g1_class(g1)}">{e(g1)}</div>'
            + (f'<div class="hd">{POINT}<span>{e(hd)}</span></div>' if hd else "")
            + (f'<div class="sub">{e(sub)}</div>' if sub else "")
            + f"</div></div>{rest}</section>")


def week_html(label, title, sub, also):
    """週まとめの札の中身（月で1位が取れなかったときもこちら）。"""
    n = len(title)
    ttsize = " long" if n > 24 else (" short" if n <= 15 else "")
    rest = ""
    if also:
        lis = "".join(f"<li>{e(x)}</li>" for x in also)
        rest = ('<div class="also">'
                f'<div class="lbl">{PLUS}こんなこともありました</div>'
                f"<ul>{lis}</ul></div>")
    return (f'<section class="card{"" if also else " solo"}">'
            f'<span class="eye">{BOLT}{e(label)}</span>'
            f'<div class="lead"><div class="hd{ttsize}">{POINT}'
            f"<span>{e(title)}</span></div>"
            + (f'<div class="sub">{e(sub)}</div>' if sub else "")
            + f"</div>{rest}</section>")


def build(col, key, theme="dark"):
    th = theme_css(theme)
    a, b, label, _slug = period(key)
    title = str(col.get("title") or "").strip()
    sub, also = card_parts(col)
    css = CSS % {"bg": th["bg"], "titlefont": th["titlefont"],
                 "textfont": th["textfont"], "titleweight": th["titleweight"],
                 "gamestroke": th["gamestroke"]}
    card = best_html(col, title, sub) if label == "月まとめ" else None
    steps = STEPS_MONTH if card else STEPS_WEEK
    if card is None:
        card = week_html(label, title, sub, also)
    return PAGE % {
        "css": css, "vars": th["vars"], "fontlink": font_link(th["fontq"]),
        "range": (a.strftime("%Y.%m") if label == "月まとめ"
                  else f"{a.strftime('%Y.%m.%d')} – {b.strftime('%m.%d')}"),
        "counts": e(week_counts(a, b)),
        "card": card,
        "note": ("YouTubeの配信タイトルを毎日自動で解析しています<br>"
                 "件数・チャンネル数は当サイトが独自に数えたものです"),
        "url": site_url(),
        "fit": FIT % {"steps": json.dumps(steps, ensure_ascii=False)},
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

        👇詳しくはサイトで
        https://hayarige.com/w/2026-09-14/

    ★は投稿文だけに足す（毎日のほうと同じ）。JSONには書かない。
    長くなったときは、削るのは1行説明のほう。見出しと
    「こんなこともありました」は残す（そこが3行サマリーの本体なので）。

    月まとめだけ、「こんなこともありました」のかわりに順位を並べる。
    カードと同じ中身にそろえてある（2026-10-01 たろちんさん）。

        9月の #ハヤリゲー ベスト3🎮

        ★『トルネコの大冒険』新作が下がっていく月に、33年前の…

        1位 トルネコの大冒険
        2位 鬼武者 Way of the Sword
        3位 モンスターストライク

        <要約>

        👇詳しくはサイトで
        https://hayarige.com/m/2026-09/

    順位は要約より先に置く。長くて削るときに落ちるのは要約のほうで、
    **順位は最後まで残す**（月まとめはそこが本体なので）。

    URLの前の1行は週も月も同じ（CTA）。カードに載るのは3行だけで、
    本文は400〜700字ある。続きがあることは文字で言わないと伝わらない。
    """
    title = str(col.get("title") or "").strip()
    if not title:
        return None
    a, b, label, slug = period(key)
    sub, also = card_parts(col)
    head = title if title.startswith("★") else "★" + title
    url = f"{CTA}\nhttps://{site_url()}/{slug}/{key}/"
    best = best_parts(col) if label == "月まとめ" else []
    if label == "月まとめ":
        kind = "ベスト3" if best else "まとめ"
        top = f"{a.month}月の #ハヤリゲー {kind}🎮\n\n{head}"
    else:
        span = f"{a.month}/{a.day}〜{b.month}/{b.day}"
        top = f"先週の #ハヤリゲー（{span}）🎮\n\n{head}"
    if best:
        # 順位は見出しのすぐ下。ここが月まとめの中身
        top += "\n\n" + "\n".join(f"{i}位 {g}"
                                  for i, (g, _n) in enumerate(best, start=1))
        also = []

    def put(sub_, also_):
        tail = ("\n\nこんなこともありました\n"
                + "\n".join("・" + x for x in also_)) if also_ else ""
        return (f"{top}\n\n{sub_}{tail}\n\n{url}" if sub_
                else f"{top}{tail}\n\n{url}")

    # 入らないときに削る順番。**上から順に試して、最初に収まったものを使う。**
    #   1 そのまま
    #   2 説明を落とす（50〜100字あるので、たいていここで収まる）
    #   3 「こんなこともありました」を後ろから1行ずつ落とす
    # 落としたものは画像には載っている。投稿から消えても読めなくはならない。
    # 見出しと（月なら）順位は最後まで残す。そこが本体なので。
    plans = [(sub, also)]
    if sub:
        plans.append(("", also))
    for k in range(len(also) - 1, 0, -1):
        plans.append(("", also[:k]))
    for sub_, also_ in plans:
        full = put(sub_, also_)
        if x_weight(full) <= 280:
            if not sub_ and sub:
                log("投稿文に入りきらないので、説明は画像だけに載せました。")
            if len(also_) < len(also):
                over = x_weight(put("", also)) - 280
                log("投稿文に入りきらないので、「こんなこともありました」の"
                    f"{len(also_) + 1}行目から下（{len(also) - len(also_)}行）は"
                    "画像だけに載せました。")
                log(f"   全部載せたいときは、合わせて約{-(-over // 2)}字"
                    "詰めてください（画像のほうは今のままで入ります）。")
            return full
    if sub:
        log("投稿文に入りきらないので、説明は画像だけに載せました。")
    return put("", also[:1] if also else [])


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
    title = str(col.get("title") or "")
    log(f"見出し: {title}（{len(title)}字）")
    log(f"説明: {sub}（{len(sub)}字）")
    if len(sub) > SUB_MAX:
        log(f"⚠️ 説明が長すぎます（目安は50〜100字、{SUB_MAX}字まで）。"
            "下の2行が押し出されます")
    elif len(sub) < SUB_MIN:
        log(f"※ 説明が短めです（目安は50〜100字）。"
            "何が起きたのかがここだけで分かる長さにしてください")

    best = best_parts(col) if kind == "月まとめ" else []
    if kind == "月まとめ":
        if not best:
            log("⚠️ 1位〜3位が見つかりません（card.best も、sections の"
                "「1位 ◯◯」もありません）。週まとめと同じ形で出します")
        for i, (g, n) in enumerate(best, start=1):
            log(f"  {i}位 {g}" + (f" ── {n}（{len(n)}字）" if n else ""))
            if i == 1 and g1_class(g):
                log("      ※ 1位の名前が長いので、札では小さく出ます。"
                    "card.best に通称を書くと大きく出せます"
                    "（『トルネコの大冒険 ちょっとステキなリマスター』→『トルネコの大冒険』）。")
            elif i > 1 and width(g) > 17:
                log("      ※ 名前が長いので2行に折り返します。"
                    "card.best に通称を書くと1行に収まります。")
            if i == 1:
                short = strip_lead_name(title, g)
                if short != title:
                    log(f"      ※ 見出しの頭の『{g}』は札では出しません"
                        f"（1位として上に大きく出るので）→「{short}」")
                elif len(best) and _flat(g) not in _flat(title):
                    log("      ※ 見出しに1位のゲーム名が入っていません。"
                        "まとめのタイトルは冒頭にゲーム名を入れる決まりです"
                        "（README_まとめ.txt）")
            elif n and len(n) > BEST_NOTE_MAX:
                log(f"      ⚠️ ひとことが長すぎます（{BEST_NOTE_MAX}字まで）。"
                    "2位・3位は横並びなので、長いと札の下がつまります")
        if best and len(best) < 3:
            log(f"※ 順位が{len(best)}つしかありません。3つ並ぶ形で作ってあります")
    else:
        if not also:
            log("こんなこともありました: なし（card.also が空です）")
        for x in also:
            log(f"  ・{x}（{len(x)}字）")
            if len(x) > ALSO_MAX:
                log(f"    ⚠️ 画像で2行に折り返します（1行は{ALSO_MAX}字まで）")

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
        where = ("1位〜3位のゲーム名を通称に縮めて" if kind == "月まとめ"
                 else "「こんなこともありました」の2行を詰めて")
        log(f"⚠️ Xの上限を {over} 文字ぶん超えています（約{-(-over // 2)}字）。"
            f"見出しを短くするか、{where}ください。")
        if kind == "月まとめ":
            log("   『トルネコの大冒険 ちょっとステキなリマスター』のような長い名前は"
                "card.best に通称を書いてください（本文の小見出しはそのままでよい）。")
        else:
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
