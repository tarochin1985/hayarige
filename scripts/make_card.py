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

from common import DATA, SITE, log, read_json, column_frame, official_handles, MENTION_HEAD


def site_url():
    """カードの右上に出す住所。data/site_config.json から読む。
    ここを決め打ちにしていたせいで、独自ドメインに移したとき
    画像だけ古いURLのままになりかけた（2026-09-21）。"""
    u = (read_json(DATA / "site_config.json", {}) or {}).get("site_url") or ""
    return u.replace("https://", "").replace("http://", "").rstrip("/") \
        or "hayarige.com"
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
    # ---- 2026-11-20 に足した4つ（文字を減らした形 card_layout: simple と合わせて見比べた）
    # 「grokの色合いのバランス結構いい感じ」（たろちんさん）。紺の題字・青の差し色・白っぽい地
    "navy": {
        "title": "gothic", "text": "gothic",
        "bg": "linear-gradient(135deg,#FFFFFF 0%,#F1F4F8 45%,#E3E9F1 100%)",
        "ink": "#1B2436", "ink2": "#4E5A6E", "ink3": "#8A94A6",
        "card": "#FFFFFF", "line": "#DDE2EA", "rail": "#E7ECF3",
        "accent": "#2B78A8", "hot": "#3466A8", "game": "#14213D", "on": "#FFFFFF",
        "sum": "#1B2436", "stroke": "", "strokec": "#14213D",
    },
    # 無彩色の地に、鮮やかな青を「ここぞ」だけ（2026-11-20。navy が青すぎたので、色味だけ直した版）
    # 地・文字・帯は白〜グレー〜チャコール。青はタイトル下の線・見出し・1位の倍率と印・URLだけ
    "clean": {
        "title": "gothic", "text": "gothic",
        "bg": "linear-gradient(135deg,#F8F9FA 0%,#F4F5F7 50%,#F1F3F5 100%)",
        "ink": "#1A1D20", "ink2": "#495057", "ink3": "#868E96",
        "card": "#FFFFFF", "line": "#DEE2E6", "rail": "#E9ECEF",
        "accent": "#2563EB", "hot": "#2563EB", "game": "#1A1D20", "on": "#FFFFFF",
        "band1": "#7A828A", "band2": "#8A9299", "rx": "#343A40",
        "sum": "#1A1D20", "stroke": "", "strokec": "#1A1D20",
    },
    # 自然で落ち着いたトーン（2026-11-20。clean の青がきつかったので「色の引き算」をした版）
    # 青（くすんだスレートブルー）は 3か所だけ: タイトル下の線の左半分・1位の棒グラフの印と「1」・1位の倍率
    "calm": {
        "title": "gothic", "text": "gothic",
        "bg": "linear-gradient(135deg,#F9F9F8 0%,#F5F5F3 50%,#F2F2F0 100%)",
        "ink": "#222528", "ink2": "#4A4F54", "ink3": "#878C91",
        "card": "#FFFFFF", "line": "#E0E0DC", "rail": "#EAEAE6",
        "accent": "#4E7D9B", "hot": "#4E7D9B", "game": "#222528", "on": "#FFFFFF",
        "band1": "#7A7F84", "band2": "#878C90", "rx": "#3A3F44",
        "hl": "#222528", "eye": "#495057", "date": "#5A6065", "ic2": "#9AA0A6",
        "dot": "rgba(0,0,0,.07)",
        "sum": "#222528", "stroke": "", "strokec": "#222528",
    },
    # ---- 「紺と青」（navy）と同じ組み立てで、色だけ変えたもの（2026-11-20 に見比べた）
    "teal": {
        "title": "gothic", "text": "gothic",
        "bg": "linear-gradient(135deg,#FFFFFF 0%,#F2F6F6 45%,#E4EEEE 100%)",
        "ink": "#17282B", "ink2": "#4A5E61", "ink3": "#859799",
        "card": "#FFFFFF", "line": "#DAE5E5", "rail": "#E5EFEF",
        "accent": "#1B8A8F", "hot": "#1B8A8F", "game": "#0F3438", "on": "#FFFFFF",
        "sum": "#17282B", "stroke": "", "strokec": "#0F3438",
    },
    # B（teal）をもとに、急上昇の倍率（1位と2〜5位）だけ F（amber）のオレンジにしたもの（2026-11-20 たろちんさんが選んだ）
    "teal_x": {
        "title": "gothic", "text": "gothic",
        "bg": "linear-gradient(135deg,#FFFFFF 0%,#F2F6F6 45%,#E4EEEE 100%)",
        "ink": "#17282B", "ink2": "#4A5E61", "ink3": "#859799",
        "card": "#FFFFFF", "line": "#DAE5E5", "rail": "#E5EFEF",
        "accent": "#1B8A8F", "hot": "#1B8A8F", "game": "#0F3438", "on": "#FFFFFF",
        "x1": "#D9792B", "rx": "#D9792B",
        "sum": "#17282B", "stroke": "", "strokec": "#0F3438",
    },
    "plum": {
        "title": "gothic", "text": "gothic",
        "bg": "linear-gradient(135deg,#FFFFFF 0%,#F5F3F7 45%,#ECE7F1 100%)",
        "ink": "#25202E", "ink2": "#5A5266", "ink3": "#958CA1",
        "card": "#FFFFFF", "line": "#E4DEEA", "rail": "#EEE9F3",
        "accent": "#6E56B0", "hot": "#6E56B0", "game": "#2A1F45", "on": "#FFFFFF",
        "sum": "#25202E", "stroke": "", "strokec": "#2A1F45",
    },
    "wine": {
        "title": "gothic", "text": "gothic",
        "bg": "linear-gradient(135deg,#FFFFFF 0%,#F8F4F2 45%,#F1E8E5 100%)",
        "ink": "#2B1E1E", "ink2": "#634F4F", "ink3": "#9E8B8B",
        "card": "#FFFFFF", "line": "#EADFDC", "rail": "#F3EAE7",
        "accent": "#A8384A", "hot": "#A8384A", "game": "#3E1620", "on": "#FFFFFF",
        "sum": "#2B1E1E", "stroke": "", "strokec": "#3E1620",
    },
    "amber": {
        "title": "gothic", "text": "gothic",
        "bg": "linear-gradient(135deg,#FFFFFF 0%,#F7F5F1 45%,#EFEAE1 100%)",
        "ink": "#22201C", "ink2": "#5B554C", "ink3": "#958E83",
        "card": "#FFFFFF", "line": "#E7E1D6", "rail": "#F1ECE3",
        "accent": "#D9792B", "hot": "#D9792B", "game": "#26231F", "on": "#FFFFFF",
        "sum": "#22201C", "stroke": "", "strokec": "#26231F",
    },
    # 白地に墨と赤。いちばん静か
    "ink": {
        "title": "gothic", "text": "gothic",
        "bg": "#FBFBFA",
        "ink": "#151515", "ink2": "#4A4A4A", "ink3": "#8C8C8C",
        "card": "#FFFFFF", "line": "#E2E2E0", "rail": "#EDEDEA",
        "accent": "#C8323C", "hot": "#C8323C", "game": "#151515", "on": "#FFFFFF",
        "sum": "#151515", "stroke": "", "strokec": "#151515",
    },
    # 深い緑と金茶。落ち着いた雑誌っぽさ
    "forest": {
        "title": "gothic", "text": "gothic",
        "bg": ("radial-gradient(1000px 700px at 90% -20%,#FFFFFF 0%,rgba(255,255,255,0) 60%),#F2F4EE"),
        "ink": "#18241D", "ink2": "#4C5C52", "ink3": "#8A978F",
        "card": "#FFFFFF", "line": "#DCE3DA", "rail": "#E6ECE3",
        "accent": "#2F6B4A", "hot": "#B7731F", "game": "#1E3A2B", "on": "#FFFFFF",
        "sum": "#18241D", "stroke": "", "strokec": "#1E3A2B",
    },
    # 濃紺の地。夜のタイムラインで目立つ
    "night": {
        "title": "gothic", "text": "gothic",
        "bg": ("radial-gradient(1100px 760px at 80% -20%,#1E3254 0%,rgba(30,50,84,0) 60%),#0E1626"),
        "ink": "#E9EEF6", "ink2": "#A5B1C5", "ink3": "#6E7C93",
        "card": "rgba(255,255,255,.06)", "line": "#26354F", "rail": "#1C2940",
        "accent": "#7FB2FF", "hot": "#F2A33A", "game": "#FFFFFF", "on": "#0E1626",
        "sum": "#E9EEF6", "stroke": "", "strokec": "#0E1626",
    },
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

.body{flex:1;display:grid;grid-template-columns:minmax(0,1fr) 560px;gap:26px;min-height:0}
/* min-width:0 が要る理由（2026-09-29）。
   グリッドや横並びの升目は、既定で「中身の最小幅より狭くならない」。
   そのため『エースコンバット8 ウイングス・オブ・シーヴ』のような長い名前が
   1つあるだけで、右の列ごと1600pxの外へ押し出され、件数とグラフが
   画像から切れていた（たろちんさんが原因まで切り分けて報告）。
   0を指定して初めて overflow や折り返しの指定が効くようになる。 */
.card{background:var(--card);border:1px solid var(--line);border-radius:18px;
  padding:24px 26px;display:flex;flex-direction:column;min-height:0;min-width:0}
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

/* 見出し。ゲーム名（hot）と本文（ink）の間を、色でもう1段つなぐ。
   頭の印は「ここだけ読めば分かる」の合図。サイト側と同じ形にしてある。 */
.hl{margin-top:14px;font-size:26px;font-weight:900;line-height:1.4;color:var(--accent);
  display:flex;gap:11px;align-items:flex-start}
.hl .pt{flex:none;width:1em;height:1em;margin-top:.24em;fill:currentColor}

/* 本文。コラムは日によって120〜480字と幅があるので、
   入りきる大きさを描画してから決める（下の FIT を見てください）。
   縮むのはここだけ。サムネイル（出典表示）は絶対に削られてはいけないので、
   flex:none で場所を先に確保し、あふれたぶんは本文側で吸収する。 */
.txt{margin-top:14px;font-size:26px;font-weight:700;line-height:1.6;color:var(--sum);
  flex:1 1 auto;min-height:0;overflow:hidden}

/* 本文が短い日は下に余白ができる。上下に均等に振って、
   サムネイルが宙に浮いて見えないようにする。 */
.pics{flex:none;margin:0 0 2px;padding-top:18px;display:flex;gap:16px}
.pics figure{width:232px;flex:none}
.pics.sm figure{width:186px}
.pics figure img{width:100%%;aspect-ratio:16/9;object-fit:cover;border-radius:10px;
  border:1px solid var(--line);display:block;background:var(--rail)}
.pics figcaption{font-size:12px;color:var(--ink3);margin-top:6px;line-height:1.45;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:700}
.pics.sm figcaption{font-size:11px}

/* 上は「1位＋グラフ」で高さが決まっている。下の一覧は5行あって、
   半分ずつに割ると入りきらず最後の行が切れる。上は中身ぶん、
   残りを下に渡す（2026-10-01）。 */
.side{display:grid;grid-template-rows:auto minmax(0,1fr);gap:26px;min-height:0;min-width:0}

/* 右下。1位のほかに伸びたゲームを並べる（2026-10-01 たろちんさん）。
   ここは長らく「今日のランキング」だったが、上位3つは前の日と
   83%%が同じ顔ぶれで、毎日見る人には新しい情報がほとんど無かった。
   急上昇のほうは同じ顔ぶれが16%%しかない。**毎日ちがうほうを出す。** */
.rise{display:flex;flex-direction:column;min-width:0}
.rise .list{display:flex;flex-direction:column;margin-top:8px;min-width:0}
.rise .r{display:grid;grid-template-columns:auto minmax(0,1fr) auto;align-items:baseline;
  gap:14px;padding:11px 0 10px;border-bottom:1px solid var(--line);min-width:0}
.rise .r:last-child{border-bottom:none}
.rise .x{font-family:"Roboto Mono",monospace;font-size:21px;font-weight:700;
  color:var(--hot);white-space:nowrap;text-align:right;min-width:74px}
.rise .nm{font-size:23px;font-weight:800;min-width:0;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.rise .ct{font-family:"Roboto Mono",monospace;font-size:15px;color:var(--ink2);white-space:nowrap}
.rise .ct em{font-style:normal;font-size:12px;color:var(--ink3)}
.row{display:grid;grid-template-columns:42px 1fr auto;align-items:center;gap:12px;
  padding:14px 0 12px;border-bottom:1px solid var(--line)}
.row:last-child{border-bottom:none}
.row .rk{font-family:%(titlefont)s;font-weight:%(titleweight)s;font-size:32px;color:var(--ink3);text-align:center;line-height:1}
.row.t1 .rk{color:var(--hot);font-size:40px}
.row .nm{font-size:24px;font-weight:800;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}
.row .ct{font-family:"Roboto Mono",monospace;font-size:17px;color:var(--ink2);white-space:nowrap}
.row .ct em{font-style:normal;font-size:13px;color:var(--ink3)}
.row .bar{grid-column:2/4;height:7px;background:var(--rail);border-radius:4px;
  overflow:hidden;margin-top:8px}
.row .bar i{display:block;height:100%%;border-radius:4px;background:var(--accent)}
.row.t1 .bar i{background:var(--hot)}

.hot{display:flex;flex-direction:column}
/* 急上昇のゲーム名。ここは主役の1つなので、1行で切らずに2行まで折り返す。
   2行で収まらないときだけ末尾を「…」にする（-webkit-line-clamp）。 */
.hot .g{font-family:%(titlefont)s;font-weight:%(titleweight)s;font-size:32px;margin-top:14px;
  line-height:1.24;color:var(--ink);min-width:0;overflow-wrap:anywhere;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.hot .g.long{font-size:27px}
.hot .g.xlong{font-size:23px}
.hot .delta span{min-width:0;overflow-wrap:anywhere}
.hot .delta{display:flex;align-items:baseline;gap:12px;margin-top:12px}
.hot .delta b{font-family:%(titlefont)s;font-weight:%(titleweight)s;font-size:44px;
  color:var(--hot);line-height:1%(numstroke)s}
.hot .delta span{font-size:16px;color:var(--ink2);font-weight:700}
.bars{display:flex;align-items:flex-end;gap:9px;height:104px;margin-top:20px}
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

# noindex を本文にも書く理由（2026-11-16）
#   Cloudflare Pages は /card.html を /card へ転送して中身を返す。
#   site/_headers の「/card.html」の行は転送の返事にしか付かず、
#   中身の /card には noindex が付いていなかった。canonical も無いので、
#   Search Console に「重複・ユーザーが正規ページを選択していません」と出た。
#   HTMLそのものに書いておけば、どの住所で読まれても効く。
PAGE = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="robots" content="noindex">
<link rel="stylesheet" href="%(fontlink)s">
<style>:root{%(vars)s}
%(css)s</style></head><body>
<header>
  <img src="logo.svg" alt="">
  <span class="nm">ハヤリゲー</span>
  <span class="tag">「次に流行るゲーム」がわかるサイト</span>
  <div class="meta"><div class="d">%(date)s</div>
    <div class="c">直近24時間 ／ 配信 %(videos)s本 ／ %(channels)sチャンネル</div></div>
</header>
<div class="body">
  <section class="card lead">%(lead)s</section>
  <div class="side">
    <section class="card hot">%(hot)s</section>
    <section class="card rise">%(rows)s</section>
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
#
# 順番:
#   1. 本文を21pxまで小さくする
#   2. それでも入らなければサムネイルを縮める（本文の場所を作る）
#   3. それでも入らなければ本文を15pxまで小さくする
#   4. まだ入らなければ本文の末尾を「…」で削る
# サムネイルは出典表示なので、どれだけ詰まっても削らない。削るのは本文だけ。
#
# 書体が届く前に測ると行数がずれるので fonts.ready を待つ。ただし
# Google Fontsが遅い・届かない環境でも必ず動くよう、6秒で見切りをつける。
# 終わったら window.__fit を立てる。--png はこれを待ってから撮る。
FIT = """
(function(){
  function run(){
    var lead=document.querySelector('.lead'),
        t=lead&&lead.querySelector('.txt'),
        pics=lead&&lead.querySelector('.pics');
    if(!t){ window.__fit=true; return; }
    function fits(){ return t.scrollHeight<=t.clientHeight+1; }
    function step(sizes){
      for(var i=0;i<sizes.length;i++){
        t.style.fontSize=sizes[i]+'px';
        if(fits()) return true;
      }
      return false;
    }
    if(!step([26,25,24,23,22,21])){
      if(pics) pics.classList.add('sm');
      if(!step([21,20,19,18,17,16,15])){
        // ここまで来たら本文が長すぎる。末尾を削って収める。
        var full=t.textContent;
        var lo=40, hi=full.length;
        while(lo<hi){
          var mid=Math.ceil((lo+hi)/2);
          t.textContent=full.slice(0,mid)+'…';
          if(fits()) lo=mid; else hi=mid-1;
        }
        t.textContent=full.slice(0,lo)+'…';
      }
    }
    // 急上昇のゲーム名。2行に収まらなければ1段ずつ小さくする。
    var g=document.querySelector('.hot .g');
    if(g){
      var gs=[32,29,27,25,23,21,19];
      var now=parseFloat(getComputedStyle(g).fontSize);
      gs=gs.filter(function(v){ return v<=now; });
      for(var k=0;k<gs.length && g.scrollHeight>g.clientHeight+1;k++)
        g.style.fontSize=gs[k]+'px';
    }
    window.__fit=true;
  }
  var ready=(document.fonts&&document.fonts.ready)||Promise.resolve();
  var giveup=new Promise(function(r){ setTimeout(r,6000); });
  Promise.race([ready,giveup]).then(run);
})();
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
# 見出しの頭に付ける印。形の定義は build_site.py に1つだけ置いてある。
from build_site import POINT
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
                f'<div class="hl">{POINT}{top.get("channels", 0)}チャンネルが配信しました</div>'
                f'<p class="txt">再生数は合わせて {man(top.get("views"))}回。</p>')
    game = str(col.get("game") or "")
    head = str(col.get("headline") or "")
    body = str(col.get("body") or "")
    pics = col.get("pics") or ([{"th": col["hero"], "by": col.get("hero_by", "")}]
                               if col.get("hero") else [])
    figs = "".join(f'<figure><img src="{e(x["th"])}" alt="">'
                   f'<figcaption>YouTube ／ {e(x.get("by"))}</figcaption></figure>'
                   for x in pics[:3])
    fr = column_frame(col)
    return (f'<span class="eye">{BOLT}{e(fr["title"]) if fr else "今日の注目ゲーム"}</span>'
            f'<div class="game{size_class(game, 13, 20)}">{e(game)}</div>'
            + (f'<div class="hl">{POINT}{e(head)}</div>' if head else "")
            + f'<p class="txt">{e(body)}</p>'
            + (f'<div class="pics">{figs}</div>' if figs else ""))


def rows_html(data):
    """右下。1位のほかに伸びたゲームを並べる。

    2026-10-01まで、ここは「今日のランキング」の上位3つだった。
    37日ぶんを数えたところ、**上位3つは前の日と83%が同じ顔ぶれ**で、
    毎日見る人には新しい情報がほとんど無かった（上位10でも71%）。
    急上昇のほうは、同じ顔ぶれが16%しかない。

    急上昇が出せない日（データの足りない日）だけ、これまでどおり順位を出す。
    """
    rising = data.get("rising") or []
    if len(rising) > 1:
        out = []
        for r in rising[1:6]:
            g = (f'<b>×{r["growth"]:.1f}</b>' if r.get("growth")
                 else f'<b>{r.get("videos", 0)}</b>')
            out.append(f'<div class="r"><span class="x">{g}</span>'
                       f'<span class="nm">{e(r.get("game"))}</span>'
                       f'<span class="ct">{r.get("channels", 0)}<em>ch</em></span></div>')
        return (f'<span class="eye tealx">{UP}ほかに伸びたゲーム</span>'
                f'<div class="list">{"".join(out)}</div>')
    # 急上昇が無い日の受け皿。開設直後など、7日ぶんの記録がそろわない日に来る
    rows = (data.get("ranking") or [])[:3]
    if not rows:
        return '<div class="r"><span class="nm">データがありません</span></div>'
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
    return f'<span class="eye tealx">{CROWN}今日のランキング</span>{"".join(out)}'


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
                f'<div class="g{size_class(r.get("game"), 14, 24)}">{e(r.get("game"))}</div>'
                f'<div class="delta">{delta}</div>'
                + bars_html(r.get("spark") or [], days))
    sp = (data.get("spread") or [{}])[0]
    return (f'<span class="eye">{UP}多くの配信者が触った</span>'
            f'<div class="g{size_class(sp.get("game"), 14, 24)}">{e(sp.get("game"))}</div>'
            f'<div class="delta"><b>{sp.get("channels", 0)}</b>'
            f'<span>チャンネルが配信</span></div>'
            + bars_html(sp.get("spark") or [], days))


# ---------------------------------------------------------------- 書体の調達
# カードはGoogle Fontsを読む前提で書いてある。GitHub Actionsからは普通に届くが、
# 画像を作っている場所（Claudeの作業環境）からは fonts.googleapis.com に
# つながらないことがある。そのとき黙って端末の既定書体に落ちるので、
# 「あなたの見せた見本と毎朝出てくる画像で書体が違う」ということが起きた。
#
# なので、届かないときは同じ書体を npm（@fontsource）から取ってきて、
# ローカルのCSSに差し替える。npmのレジストリはどちらの環境からも届く。
# 取れなかったときは黙って落ちず、はっきりログに出す。
FONT_CACHE = Path.home() / ".cache" / "hayarige-fonts"


def families_of(fontq):
    """Google Fontsへの指定（'Zen+Maru+Gothic:wght@500;700;900'）から書体名を取り出す。"""
    return [q.split(":")[0].replace("+", " ") for q in fontq.split("&family=")]


def google_reachable(url):
    import urllib.request
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            return r.status == 200
    except Exception:
        return False


def local_font_css(families):
    """@fontsource から書体を落として、1枚のCSSにまとめる。作れなければ None。"""
    import subprocess
    pkgs = [f.lower().replace(" ", "-") for f in families]
    FONT_CACHE.mkdir(parents=True, exist_ok=True)
    have = FONT_CACHE / "node_modules" / "@fontsource"
    need = [k for k in pkgs if not (have / k).is_dir()]
    if need:
        log(f"書体を取ってきます（{'・'.join(need)}）")
        r = subprocess.run(["npm", "install", "--silent", "--no-audit", "--no-fund"]
                           + [f"@fontsource/{k}" for k in need],
                           cwd=FONT_CACHE, capture_output=True, text=True)
        if r.returncode != 0:
            log("書体を取ってこられませんでした: " + (r.stderr or "")[:200])
            return None
    out = []
    for k in pkgs:
        # index.css は太さ400だけ。カードは500〜900を使うので、ある太さを全部読む
        # （2026-11-20。400だけだと見本の題字が細く出て、本番と見え方が違った）
        csss = [have / k / f"{w}.css" for w in ("400", "500", "700", "800", "900")
                if (have / k / f"{w}.css").is_file()] or [have / k / "index.css"]
        if not csss[0].is_file():
            log(f"書体の中身が見つかりません: {k}")
            return None
        for css in csss:
            out.append(css.read_text(encoding="utf-8")
                       .replace("url(./files/", f"url(file://{(have / k).resolve()}/files/"))
    path = FONT_CACHE / "card-fonts.css"
    path.write_text("\n".join(out), encoding="utf-8")
    return path


def font_link(fontq):
    """<link> のURLを決める。Google Fontsが届くならそのまま、駄目ならローカル。"""
    url = f"https://fonts.googleapis.com/css2?family={fontq}&display=swap"
    if google_reachable(url):
        return url
    log("Google Fontsに届きませんでした。同じ書体をローカルから読みます。")
    path = local_font_css(families_of(fontq))
    if path:
        return "file://" + str(path.resolve())
    log("警告: 指定した書体が使えません。この画像は見本と違う書体で出ます。")
    return url


def theme_css(name):
    """テーマ名から、CSSの変数と書体の指定を作る。"""
    th = THEMES.get(name) or THEMES["dark"]
    tf, txf = FONTS[th["title"]], FONTS[th["text"]]
    fontq = "&family=".join(dict.fromkeys(
        [tf[0], txf[0], "Roboto+Mono:wght@500;700"]))
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
    # ゲーム名だけ別の色にしたいテーマ（2026-11-20 に足した「navy」など）。無ければ hot
    if th.get("game"):
        vars_ += f";--game:{th['game']}"
    # 右のカードの帯の色（無ければ game → accent のグラデーション）、2〜5位の倍率の色（無ければ hot）
    for k in ("band1", "band2", "rx", "hl", "eye", "date", "ic2", "dot", "x1"):
        if th.get(k):
            vars_ += f";--{k}:{th[k]}"
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
        "css": css, "vars": th["vars"], "fontlink": font_link(th["fontq"]),
        "crown": CROWN,
        "date": e(str(data.get("date", "")).replace("-", ".")),
        "videos": t.get("videos", 0), "channels": t.get("channels", 0),
        "lead": lead_html(data.get("column"), data.get("ranking") or []),
        "rows": rows_html(data),
        "hot": hot_html(data),
        "note": note, "url": site_url(), "fit": FIT,
    }


# ---------------------------------------------------------------- 文字を減らした形
# 2026-11-20 たろちんさん。
#
#   > 現在は画像内の文字量が多すぎて読者の負担が大きいと思った。grokに説明文を短くし、
#   > 右側にランキング情報を残したバージョンの画像を作ってもらった。配置や文字数の塩梅などは
#   > これくらいがいいんじゃないかと思った。
#
# 本文をまるごと載せるのをやめて、**ゲーム名・見出し・1文だけ**にする。
# 右は急上昇の上位5つ（1位だけ大きく。サムネイルの大きさでも読めるよう、字を大きめに）。下にサムネイル3枚を横いっぱいに。
# data/site_config.json の card_layout が "simple" のとき、こちらを使う
# （"classic" か空なら今までの形）。見比べたいときは --layout=simple。
CSS_SIMPLE = """
*{box-sizing:border-box;margin:0;padding:0}
body{width:1600px;height:900px;overflow:hidden;color:var(--ink);background:%(bg)s;
  font-family:%(textfont)s;padding:30px 44px 24px;display:flex;flex-direction:column;gap:16px;position:relative}
/* 地の質感（2026-11-20）。ベタ塗りにしない。ごく薄い斜めの光と、目立たないドット */
body::before{content:"";position:absolute;inset:0;pointer-events:none;z-index:0;
  background:linear-gradient(135deg,rgba(255,255,255,.55) 0%%,rgba(255,255,255,0) 45%%),
    radial-gradient(circle,var(--dot,var(--line)) 1.1px,transparent 1.6px) 0 0/22px 22px;opacity:.55}
body>*{position:relative;z-index:1}
header{display:flex;align-items:center;gap:14px;flex:none}
header img{width:42px;height:42px;object-fit:contain}
header .nm{font-family:%(titlefont)s;font-weight:%(titleweight)s;font-size:25px}
header .tag{font-size:14px;color:var(--ink2);font-weight:700}
header .meta{margin-left:auto;text-align:right}
header .d{font-family:"Roboto Mono",monospace;font-size:24px;font-weight:700;color:var(--date,var(--accent));line-height:1}
header .c{font-size:12px;color:var(--ink2);margin-top:5px;font-weight:700}
.mid{flex:1;display:grid;grid-template-columns:minmax(0,1fr) 640px;gap:30px;min-height:0}
.lead{display:flex;flex-direction:column;justify-content:center;min-width:0;min-height:0;overflow:hidden;padding-left:6px}
.eye{align-self:flex-start;display:inline-flex;align-items:center;gap:8px;
  font-family:%(titlefont)s;font-weight:%(titleweight)s;font-size:16px;color:var(--on);background:var(--eye,var(--hot));
  padding:6px 14px 6px 12px;border-radius:8px;box-shadow:0 4px 10px -4px rgba(15,30,60,.35)}
.eye svg{width:16px;height:16px}
/* ゲーム名。前の1.4倍。字間を少し詰めて力強く。2行に入らなければ FIT が縮める */
.game{font-family:%(titlefont)s;font-weight:%(titleweight)s;font-size:136px;line-height:1.04;
  margin-top:14px;letter-spacing:-.035em;color:var(--game,var(--hot))%(gamestroke)s;
  word-break:auto-phrase;text-wrap:balance}
/* 2色の太い線。左が差し色、右が淡い色 */
.rule{height:6px;width:58%%;margin:22px 0 0;border-radius:3px;
  background:linear-gradient(90deg,var(--accent) 0 34%%,var(--rail) 34%% 100%%)}
.hl{margin-top:20px;padding-bottom:18px;border-bottom:1.5px dashed var(--line);
  font-size:34px;font-weight:900;line-height:1.38;color:var(--hl,var(--accent));
  display:flex;gap:12px;align-items:flex-start}
.hl .pt{flex:none;width:1em;height:1em;margin-top:.22em;fill:currentColor}
/* 日本語を文節で折り返す（Chrome の auto-phrase）。balance だけだと単語の途中で割れる */
.hl span{word-break:auto-phrase;text-wrap:balance}
/* 1文目と、頭の印（2色使いのコントローラー。絵文字は書体で形が変わるので自前で描く） */
.one{margin-top:18px;display:flex;gap:16px;align-items:center}
.one .ic{flex:none;width:80px;height:80px;border-radius:20px;background:var(--card);
  border:1px solid var(--line);box-shadow:0 8px 18px -10px rgba(15,30,60,.45);
  display:flex;align-items:center;justify-content:center}
.one .ic svg{width:56px;height:56px}
.one .ic .c1{fill:var(--game,var(--accent))}
.one .ic .c2{fill:var(--ic2,var(--accent))}
.one .ic .c3{fill:var(--card)}
.one p{font-size:23px;font-weight:700;line-height:1.55;color:var(--ink2);
  max-height:3.2em;overflow:hidden;word-break:auto-phrase;text-wrap:pretty}
/* 右のカード。天面いっぱいに帯を敷く */
.rank{background:var(--card);border:1px solid var(--line);border-radius:18px;overflow:hidden;
  display:flex;flex-direction:column;min-width:0;min-height:0;
  box-shadow:0 22px 44px -26px rgba(15,30,60,.45),0 2px 6px -2px rgba(15,30,60,.12)}
.band{flex:none;display:flex;align-items:center;gap:10px;padding:11px 26px;
  background:linear-gradient(90deg,var(--band1,var(--game,var(--hot))),var(--band2,var(--accent)));
  color:#fff;font-family:%(titlefont)s;font-weight:%(titleweight)s;font-size:21px;letter-spacing:.06em}
.band svg{width:22px;height:22px;fill:#fff}
.rbody{padding:4px 28px 10px;display:flex;flex-direction:column;justify-content:space-between;flex:1;min-height:0}
.r1{display:grid;grid-template-columns:auto minmax(0,1fr) auto;align-items:center;gap:18px;
  padding:11px 0 10px;border-bottom:1px solid var(--line)}
.r1 .bi{position:relative;width:76px;height:76px;border-radius:50%%;background:var(--rail);display:flex;
  align-items:center;justify-content:center}
/* 2〜5位の数字とそろえる「1」の札 */
.r1 .bi b{position:absolute;right:-4px;top:-4px;min-width:28px;height:28px;border-radius:14px;
  background:var(--accent);color:#fff;font-family:"Roboto Mono",monospace;font-size:17px;font-weight:700;
  display:flex;align-items:center;justify-content:center;border:2px solid var(--card)}
.r1 .bi svg{width:40px;height:40px;fill:var(--accent)}
.r1 .nm{font-size:40px;font-weight:900;line-height:1.15;overflow-wrap:anywhere}
.r1 .nm small{display:block;font-size:17px;color:var(--ink2);font-weight:700;margin-top:7px}
.r1 .x{font-family:"Roboto Mono",monospace;font-weight:700;font-size:84px;color:var(--x1,var(--hot));line-height:1;
  letter-spacing:-.04em%(numstroke)s}
.r{display:grid;grid-template-columns:34px minmax(0,1fr) auto auto;gap:14px;align-items:baseline;
  padding:8px 0;border-bottom:1px solid var(--line)}
.r:last-child{border-bottom:0}
.r .k{font-family:"Roboto Mono",monospace;font-weight:700;font-size:24px;color:var(--ink3)}
.r .nm{font-size:29px;font-weight:800;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
.r .x{font-family:"Roboto Mono",monospace;font-weight:700;font-size:30px;color:var(--rx,var(--hot))}
.r .ct{font-size:17px;color:var(--ink2);font-weight:700;min-width:52px;text-align:right}
/* 下のサムネイル。上に文字は重ねない（サムネイルはそのまま見せる）。白いフチと深い影で写真のように */
/* ★サムネイルは YouTube と同じ 16:9 のまま見せる（2026-11-21）。前は高さ200pxの横長の枠に
   object-fit:cover で入れていたので、上下が切れていた（たろちんさん「下側がちょっと切れている」。
   サムネイルの下には大きな文字が入っていることが多い）。幅を決めて、高さは 16:9 で決まる */
.pics{flex:none;display:flex;justify-content:space-between;padding:0 4px}
.pics figure{width:440px;min-width:0}
.pics figure img{width:100%%;aspect-ratio:16/9;height:auto;object-fit:cover;border-radius:12px;display:block;
  background:var(--rail);border:3px solid #fff;
  box-shadow:0 18px 34px -16px rgba(15,30,60,.55),0 3px 8px -3px rgba(15,30,60,.25)}
.pics figcaption{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-top:10px}
.pics figcaption .ch{font-size:13px;font-weight:700;color:var(--ink2);background:var(--rail);
  border-radius:99px;padding:4px 12px;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:80%%}
.pics figcaption .url{font-size:14px;font-weight:700;color:var(--date,var(--accent));flex:none}
"""

PAGE_SIMPLE = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="robots" content="noindex">
<link rel="stylesheet" href="%(fontlink)s">
<style>:root{%(vars)s}
%(css)s</style></head><body>
<header>
  <img src="logo.svg" alt="">
  <span class="nm">ハヤリゲー</span>
  <span class="tag">「次に流行るゲーム」がわかるサイト</span>
  <div class="meta"><div class="d">%(date)s</div>
    <div class="c">直近24時間 ／ 配信 %(videos)s本 ／ %(channels)sチャンネル</div></div>
</header>
<div class="mid">
  <section class="lead">%(lead)s</section>
  <section class="rank">%(rank)s</section>
</div>
%(pics)s
<script>%(fit)s</script>
</body></html>
"""

# ゲーム名が2行に入らなければ1段ずつ小さくする。左の列からはみ出すときも小さくする。
FIT_SIMPLE = """
(function(){
  // 行数は「高さ ÷ 行の高さ」で数える
  // （フチ付きの書体は scrollHeight がはみ出して見えるので、そちらでは測らない）
  function lines(el){
    var lh=parseFloat(getComputedStyle(el).lineHeight)||1;
    return Math.round(el.getBoundingClientRect().height/lh);
  }
  function shrink(el, sizes, ok){
    if(!el) return;
    for(var i=0;i<sizes.length && !ok(el);i++)
      el.style.fontSize=sizes[i]+'px';
  }
  function run(){
    var lead=document.querySelector('.lead'), g=lead&&lead.querySelector('.game');
    var two=function(el){ return lines(el)<=2; };
    shrink(g,[124,112,100,90,80,72,64,56,50,46],function(el){
      return two(el) && lead.scrollHeight<=lead.clientHeight+1; });
    shrink(document.querySelector('.lead .hl span'),[32,30,28,26],two);
    shrink(document.querySelector('.r1 .nm'),[36,33,30,27,24,22],two);
    window.__fit=true;
  }
  var ready=(document.fonts&&document.fonts.ready)||Promise.resolve();
  var giveup=new Promise(function(r){ setTimeout(r,6000); });
  Promise.race([ready,giveup]).then(run);
})();
"""


# コントローラーの印。2色使い（本体＝差し色、ボタン＝もう1色、十字キー＝地の色）。自前で描いたもの
PAD = ('<svg viewBox="0 0 48 48" aria-hidden="true">'
       '<path class="c1" d="M15 12h18a11 11 0 0 1 10.8 13l-1.9 9.6a5.4 5.4 0 0 1-9.4 2.6L28.6 32H19.4'
       'l-3.9 5.2a5.4 5.4 0 0 1-9.4-2.6L4.2 25A11 11 0 0 1 15 12z"/>'
       '<path class="c3" d="M13.6 18.5h3v4h4v3h-4v4h-3v-4h-4v-3h4z"/>'
       '<circle class="c2" cx="33" cy="19.6" r="2.4"/><circle class="c2" cx="37.4" cy="24" r="2.4"/>'
       '<circle class="c3" cx="28.6" cy="24" r="2.4"/><circle class="c3" cx="33" cy="28.4" r="2.4"/></svg>')
# 1位の行の左に置く棒グラフの印（3本）
BARS = ('<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="13" width="4.6" height="8" rx="1.2"/>'
        '<rect x="9.7" y="8" width="4.6" height="13" rx="1.2"/><rect x="16.4" y="3" width="4.6" height="18" rx="1.2"/></svg>')


def lead_simple(col, ranking):
    if not col:
        top = (ranking or [{}])[0]
        return (f'<span class="eye">{BOLT}今日いちばん配信されたゲーム</span>'
                f'<div class="game">{e(top.get("game"))}</div><div class="rule"></div>'
                f'<div class="hl">{POINT}<span>{top.get("channels", 0)}チャンネルが配信しました</span></div>')
    fr = column_frame(col)
    one = first_line(col.get("body"))
    return (f'<span class="eye">{BOLT}{e(fr["title"]) if fr else "今日の注目ゲーム"}</span>'
            f'<div class="game">{e(col.get("game"))}</div><div class="rule"></div>'
            + (f'<div class="hl">{POINT}<span>{e(col.get("headline"))}</span></div>' if col.get("headline") else "")
            + (f'<div class="one"><span class="ic">{PAD}</span><p>{e(one)}</p></div>' if one else ""))


def rank_simple(data):
    """右。天面に帯を敷き、急上昇の上位5つ。1位だけ大きく、倍率を主役にする。"""
    rising = data.get("rising") or []
    if not rising:
        rows = (data.get("ranking") or [])[:5]
        out = "".join(f'<div class="r"><span class="k">{i}</span><span class="nm">{e(r.get("game"))}</span>'
                      f'<span class="x">{r.get("videos", 0)}件</span>'
                      f'<span class="ct">{r.get("channels", 0)}ch</span></div>'
                      for i, r in enumerate(rows, 1))
        return f'<div class="band">{CROWN}今日のランキング</div><div class="rbody">{out}</div>'
    r = rising[0]
    base = r.get("base")
    sub = (f'ふだん {base:g}件 → 今日 {r.get("videos", 0)}件 ／ {r.get("channels", 0)}ch'
           if base is not None else f'{r.get("channels", 0)}チャンネルが配信')
    out = [f'<div class="r1"><span class="bi">{BARS}<b>1</b></span>'
           f'<div class="nm">{e(r.get("game"))}<small>{e(sub)}</small></div>'
           f'<span class="x">×{(r.get("growth") or 1):.1f}</span></div>']
    for i, x in enumerate(rising[1:5], 2):
        g = f'×{x["growth"]:.1f}' if x.get("growth") else f'{x.get("videos", 0)}件'
        out.append(f'<div class="r"><span class="k">{i}</span><span class="nm">{e(x.get("game"))}</span>'
                   f'<span class="x">{g}</span><span class="ct">{x.get("channels", 0)}ch</span></div>')
    return f'<div class="band">{UP}今日の急上昇</div><div class="rbody">{"".join(out)}</div>'


def pics_simple(col):
    pics = (col or {}).get("pics") or ([{"th": col["hero"], "by": col.get("hero_by", "")}]
                                       if (col or {}).get("hero") else [])
    if not pics:
        return ""
    figs = []
    for i, x in enumerate(pics[:3]):
        last = (i == min(len(pics), 3) - 1)
        figs.append(f'<figure><img src="{e(x["th"])}" alt="">'
                    f'<figcaption><span class="ch">YouTube ／ {e(x.get("by"))}</span>'
                    + (f'<span class="url">{e(site_url())}</span>' if last else "")
                    + '</figcaption></figure>')
    return f'<div class="pics">{"".join(figs)}</div>'


def build_simple(data, theme="cream"):
    t = data.get("totals") or {}
    th = theme_css(theme)
    css = CSS_SIMPLE % {"bg": th["bg"], "titlefont": th["titlefont"],
                        "textfont": th["textfont"], "titleweight": th["titleweight"],
                        "gamestroke": th["gamestroke"], "numstroke": th["numstroke"]}
    col = data.get("column")
    return PAGE_SIMPLE % {
        "css": css, "vars": th["vars"], "fontlink": font_link(th["fontq"]),
        "date": e(str(data.get("date", "")).replace("-", ".")),
        "videos": t.get("videos", 0), "channels": t.get("channels", 0),
        "lead": lead_simple(col, data.get("ranking") or []),
        "rank": rank_simple(data), "pics": pics_simple(col), "fit": FIT_SIMPLE}


# ---------------------------------------------------------------- 投稿文
# 画像と一緒に、Xに貼る文もここで作る。
# 毎朝これを手で打ち直していると、日付やかぎかっこを取り違える。
# 中身は全部 site/data.json に入っているので、機械で組み立てたほうが確実。

def x_weight(text):
    """Xの文字数の目安。日本語と絵文字は2文字ぶん、URLは長さに関係なく
    23文字ぶんで数える。上限は280。厳密な仕様の近似なので目安として使う。"""
    t = re.sub(r"https?://\S+", "x" * 23, text)
    return sum(1 if ord(c) < 0x1100 else 2 for c in t)


SUM_MAX = 60      # 投稿文に足す1行サマリーの上限（字）。
                  # これより長い1文目は、要約ではなく本文なので足さない


def first_line(body):
    """本文の1文目。投稿文に足す1行サマリーに使う。

    なぜ本文の1文目でよいのか（2026-10-05に実物を見て確かめた）
    ----------------------------------------------------------
    直近5日ぶんを並べたら、どれも26〜34字で、**見出しと噛み合っていた。**

        見出し  毎回ちがう顔ぶれが、同じ助手席に座る
        1文目   プレイヤーは助手席にいて、運転席の妹に声で運転を教えるゲーム。

    EDITORIAL.md 5章で「本文はAどんなゲームか→Bどう配信されているか」の順に
    書くと決めてあるので、**1文目はたいていAの説明になる。**
    見出し（その日の面白いところ＝B寄り）と役割が重なりにくい。
    書く人の手間も増えない。

    ※ Bから書き始めた日は、見出しと似た話になることがある。
      そのときは貼る前に手で削ってよい（投稿文は手でコピーして使うため）。
    """
    t = re.split(r"(?<=[。！？])", str(body or "").strip())
    s = (t[0] if t else "").strip()
    return s if 0 < len(s) <= SUM_MAX else ""


def tweet_text(data):
    """Xに貼る投稿文を組み立てる。
    （2026-09-22 たろちんさんと決めた形。変えるときは本人に確認すること）

        今日の注目ゲームは『妹に運転を教える』🎮

        ★毎回ちがう顔ぶれが、同じ助手席に座ってる

        プレイヤーは助手席にいて、運転席の妹に声で運転を教えるゲーム。

        https://hayarige.com/d/2026-09-21/

    2026-10-05に、たろちんさんと3か所変えた
    ----------------------------------------
    1. **`#ハヤリゲー` を外した。** 使っているのがほぼ自分だけのタグで、
       そこから人は来ない。それを毎日同じ位置に置くことが、
       「毎日同じ型」をいちばん作っていた。企画の回に見出しへ入れる
       `#マイクラ肝試し2026` のようなタグ（EDITORIAL.md 5章）は、
       追っている人が実在するので**そちらは残す。**
    2. **1行サマリーを足した。** 投稿ごとに違う文が1つ増える。
       読む人にとっても、見出しだけより何の話か分かる。
    3. **リンクをトップからその日のページに変えた。** トップを指すと、
       **1週間後にその投稿から来た人は別の日のコラムに着く。**
       サイトの「このコラムを共有」ボタンは前から /d/ を指していて、
       投稿文だけがトップのままだった（build_site.py の share_col と同じ理由）。

    見出しの頭の ★ は、ここで足す（2026-09-23 追加）。
    コラムのJSONには入れない。見出しはサイトと画像にも同じものが出るので、
    JSONに★を書くと3か所すべてに出てしまう。★が欲しいのは投稿文だけ。

    コラムが無い日は None を返す。"""
    col = data.get("column") or {}
    game = str(col.get("game") or "").strip()
    head = str(col.get("headline") or "").strip()
    d = str(col.get("date") or data.get("date") or "")
    if not game or not head or len(d) < 10:
        return None
    if not head.startswith("★"):           # すでに付いていたら重ねない
        head = "★" + head
    summary = first_line(col.get("body"))
    # ★「推し」の枠の日は1行目が変わる（2026-11-19。呼び方は common.py の FRAMES）
    fr = column_frame(col)
    first = fr["tweet"].format(game=game) if fr else f"今日の注目ゲームは『{game}』🎮"
    out = [first, "", head]
    if summary:
        out += ["", summary]
    # ★インディーの日は公式アカウントを入れる（2026-11-19）。開発元に届くと
    #   引用で広めてもらえることがある。URLの前に置く（URLのカードが最後に来るように）
    hs = official_handles(col)
    if hs:
        out += ["", MENTION_HEAD + " ".join("@" + h for h in hs)]
    out += ["", f"https://{site_url()}/d/{d}/"]
    return "\n".join(out)


def write_tweet(data):
    """投稿文を site/tweet.txt に置く。画像と同じように公開URLからも
    取れるので、スマホで開いてそのままコピーできる。
    コラムが無い日は、前の日の文が残らないように消す。"""
    path = SITE / "tweet.txt"
    text = tweet_text(data)
    if not text:
        path.unlink(missing_ok=True)
        log("今日のコラムがまだ無いので、投稿文は作りませんでした。")
        return None
    path.write_text(text + "\n", encoding="utf-8")
    n = x_weight(text)
    log(f"投稿文を書き出しました: {path}（約{n}文字ぶん／上限280）")
    if n > 280:
        log("⚠️ Xの上限を超えています。見出しを短くするか、投稿を分けてください。")
    log("---- ここから投稿文 ----")
    log(text)
    log("---- ここまで ----")
    return text


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
    layout = cfg.get("card_layout") or "classic"
    for a in sys.argv[1:]:
        if a.startswith("--layout="):
            layout = a.split("=", 1)[1]
    out = SITE / f"{out_name}.html"
    out.write_text(build_simple(data, theme) if layout == "simple" else build(data, theme),
                   encoding="utf-8")
    log(f"カードを書き出しました: {out}（テーマ {theme}・形 {layout}）")

    # 投稿文は画像より先に作る。画像は書体やサムネイルが取れないと失敗するが、
    # 文のほうは data.json だけで作れるので、失敗する日でも渡せる。
    # 見本を作っているだけのとき（--out=）は本番の文を上書きしない。
    if out_name == "card":
        write_tweet(data)

    if "--png" in sys.argv:
        from playwright.sync_api import sync_playwright
        png = SITE / f"{out_name}.png"
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": 1600, "height": 900},
                            device_scale_factor=1)
            pg.goto("file://" + str(out.resolve()))
            # 待ち時間を決め打ちにしていたら、書体の到着が遅い日に
            # 文字の大きさを詰める前に撮ってしまい、サムネイルが画面の外に
            # はみ出したまま出た（2026-09-06）。詰め終わった合図を待つ。
            try:
                pg.wait_for_function("window.__fit === true", timeout=20000)
            except Exception:
                log("文字の大きさを詰める処理が終わりませんでした。そのまま撮ります。")
            pg.wait_for_timeout(400)           # 画像の読み込みが終わるのを少し待つ
            # ここから下は「出せる画像かどうか」の確認。
            # 2026-09-06に、書体が別物・サムネイル空欄の画像がそのまま出てしまった。
            # 見て気づけない種類の崩れなので、機械で止める。
            ng = []
            # 画像が届ききるのを待ってから数える
            try:
                pg.wait_for_function(
                    """() => [...document.querySelectorAll('.pics img')]
                        .every(i => i.complete)""", timeout=15000)
            except Exception:
                pass
            miss = pg.evaluate("""() => [...document.querySelectorAll('.pics img')]
                .filter(i => !i.complete || i.naturalWidth === 0).length""")
            if miss:
                ng.append(f"配信サムネイル {miss} 枚が読み込めていません"
                          "（i.ytimg.com に出られていない）")
            # 書体の確認に document.fonts.check は使えない。あれは太さ400を
            # 探しにいくが、Google Fontsからは指定した太さ（500/700/900）しか
            # 届かないので、正しく表示できている日でも「無い」と答えてしまう。
            # 実際に読み込まれた書体の一覧を見るほうが確か。
            loaded = pg.evaluate("""() => [...document.fonts]
                .filter(f => f.status === 'loaded').map(f => f.family)""")
            for fam in families_of(theme_css(theme)["fontq"]):
                if fam not in loaded:
                    ng.append(f"書体「{fam}」が当たっていません")
            if ng and "--force" not in sys.argv:
                # 投稿に使えないので、card.png としては書かない。
                # 配置だけ見たいときのために別名で残す。
                prev = SITE / f"{out_name}_preview.png"
                pg.screenshot(path=str(prev))
                b.close()
                for x in ng:
                    log("  ・" + x)
                log(f"この環境では投稿用の画像を作れません。配置の確認用に {prev} だけ残しました。")
                log("投稿用の画像は Actions →「3. 毎日の更新」→ Run workflow で作られ、"
                    "site/card.png に入ります。")
                return 2
            pg.screenshot(path=str(png))
            b.close()
        # 前に失敗したときの見本が残っていると、どちらが新しいか分からなくなる
        (SITE / f"{out_name}_preview.png").unlink(missing_ok=True)
        log(f"画像を書き出しました: {png}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
