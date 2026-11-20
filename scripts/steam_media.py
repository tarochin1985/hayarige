#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""紹介ツイートに使う、公式の画像・動画の候補を集める（2026-11-19）。

なぜ作ったか
------------
> 公式の画像素材が使えるなら使ったほうがいい。URLから自動で出るOGP画像って
> 人間から見るとあんまり目を引かないものとかやっぱ多いのよ。公式素材でも
> キャッチーな画像（あるいは動画）が1枚あるかどうか、文言とのシナジーがあるか
> どうかでバズるかどうかは全く変わる。仕組みとして探して持ってこれるならそうしておきたい
> （2026-11-19 たろちんさん）

何をするか
----------
急上昇・新作ウォッチ・順位表の上のほうのゲームについて、Steamのストアに
**公式が載せているスクリーンショットとトレーラー**の住所（URL）を集めて、

  ・data/steam_media.json      … 住所の一覧（朝の窓が読む）
  ・site/admin/media.html      … たろちんさんがスマホで見て選ぶページ

を書き出す。**画像そのものは保存しない**（ページは Steam の住所をそのまま表示する）。
写しを持たないので、こちらのサイトから配っていることにはならない。

★この作業環境（Claude）からは Steam につながらないので、毎日の更新（GitHub Actions）の
  中で `steam_reviews.py` の最後に呼ばれる。失敗しても何も壊さない。

★使ってよいかの線は、朝の手順「■ 紹介ツイート」に書いてある
  （ストアの素材は権利者が宣伝のために公開しているもの。ゲーム名・公式の@・
   ストアのリンクを添えて紹介に使う。プレスキットに条件があればそれに従う）。
"""
import html
import json
import re
import time
from datetime import datetime, timedelta
from urllib import request
from urllib.parse import unquote

from common import DATA, SITE, JST, log, read_json, write_json

OUT = DATA / "steam_media.json"
PAGE = SITE / "admin" / "media.html"
SHOTS = 8           # 1ゲームあたり、残すスクリーンショットの数
KEEP_DAYS = 14      # 何日前に取ったものまで残すか
MAX_GAMES = 24      # 1回で見に行くゲームの数の上限（1.2秒ずつ空ける）


# ---- 公式X（2026-11-21）------------------------------------------------------
# 朝の窓が『牛丼店シミュレーター』の公式Xを見つけられなかった（Steamに公式サイトの住所が無い）。
# たろちんさんが AUTOMATON の記事に埋め込まれた開発元のツイートから見つけた（@whitegame1030）。
#
# > これくらいは自分で探せるようになってくれると嬉しい（2026-11-21 たろちんさん）
#
# Steam の API（appdetails）には「ソーシャルのリンク」が入っていない。ストアのページには
# 開発元が登録した X・YouTube・Discord などのリンクが出ているので、**毎日の更新（Actions）が
# ストアのページ・説明文・公式サイトを読んで、X の住所を拾っておく。** 朝の窓はこれを先に見る。
# どこで拾ったかも残す（ストアのページ ＞ 説明文 ＞ 公式サイト の順に確か）。
X_RE = re.compile(r"(?:https?:)?//(?:www\.|mobile\.)?(?:x|twitter)\.com/(?:#!/)?@?"
                  r"([A-Za-z0-9_]{1,15})(?![A-Za-z0-9_])", re.I)
# アカウントではない住所（共有ボタンなど）と、Steam 自身のアカウント
NOT_HANDLE = {"intent", "share", "home", "search", "hashtag", "i", "settings", "login",
              "signup", "explore", "tos", "privacy", "messages", "notifications",
              "steam", "steamdb", "valvesoftware", "steamstudio"}
LINKFILTER = re.compile(r"linkfilter/?\?(?:u|url)=([^\"'&<>\s]+)", re.I)
UA = {"User-Agent": "hayarige-bot (+https://hayarige.com/)",
      # 年齢確認のページで止まらないように（ストアのページを読むだけ）
      "Cookie": "birthtime=0; lang=japanese; wants_mature_content=1",
      "Accept-Language": "ja,en;q=0.5"}


def _get_text(url, limit=2_000_000):
    """ページの文字。取れなければ ""（失敗しても何も壊さない）。"""
    try:
        with request.urlopen(request.Request(url, headers=UA), timeout=20) as r:
            return r.read(limit).decode("utf-8", "ignore")
    except Exception:
        return ""


def x_handles(text):
    """文字の中の X のアカウント名（重ならない・出てきた順）。住所が符号化されていても拾う。"""
    out, seen = [], set()
    for t in (text or "", unquote(unquote(text or ""))):
        for m in X_RE.finditer(t):
            h = m.group(1)
            if h.lower() in NOT_HANDLE or h.lower() in seen:
                continue
            seen.add(h.lower())
            out.append(h)
    return out


def official_x(appid, d):
    """[{"handle": ..., "どこから": ...}]。いちばん確かなところで拾ったものを先に。"""
    got, seen = [], set()

    def put(hs, where):
        for h in hs:
            if h.lower() not in seen:
                seen.add(h.lower())
                got.append({"handle": h, "どこから": where})
    # 1. ストアのページの、開発元が登録したリンク（Steam は外へのリンクを linkfilter で包む。
    #    Steam 自身のリンクは包まれないので、包まれたものだけ見れば開発元のリンクだけになる）
    time.sleep(1.0)
    page = _get_text(f"https://store.steampowered.com/app/{appid}/?l=japanese")
    page = page.replace("\\/", "/")             # ページに埋め込まれたデータの中は / が \/ になっている
    put(x_handles(" ".join(LINKFILTER.findall(page))), "Steamのストアのページ")
    if not got:
        # リンクの形が変わっていたときの控え。ページ全体から拾うので、少し確かさが下がる
        put(x_handles(page), "Steamのストアのページ（ページ内の住所。念のため確かめる）")
    # 2. ストアの説明文
    put(x_handles((d.get("detailed_description") or "") + (d.get("about_the_game") or "")),
        "Steamの説明文")
    # 3. 公式サイト（Steam の住所のときは見ない）
    web = d.get("website") or ""
    if web.startswith("http") and "steampowered.com" not in web and "steamcommunity.com" not in web:
        put(x_handles(_get_text(web)), "公式サイト")
    return got[:4]


def e(s):
    return html.escape(str(s if s is not None else ""), quote=True)


def _urls(v):
    """動画の欄は形がいろいろある（mp4 / webm / hls / dash）。中の住所を全部拾う。"""
    out = []
    if isinstance(v, str) and v.startswith("http"):
        out.append(v)
    elif isinstance(v, dict):
        for x in v.values():
            out += _urls(x)
    elif isinstance(v, list):
        for x in v:
            out += _urls(x)
    return out


def fetch(appid, get_json):
    url = (f"https://store.steampowered.com/api/appdetails?appids={appid}"
           "&cc=jp&l=japanese")
    res, why = get_json(url)
    if not isinstance(res, dict):
        return None, why
    d = (res.get(str(appid)) or {})
    if not d.get("success"):
        return None, "success=false"
    d = d.get("data") or {}
    shots = [{"thumb": s.get("path_thumbnail"), "full": s.get("path_full")}
             for s in (d.get("screenshots") or [])[:SHOTS]
             if s.get("path_full")]
    movies = []
    for m in (d.get("movies") or [])[:4]:
        urls = _urls({k: v for k, v in m.items() if k not in ("thumbnail", "id", "name")})
        mp4 = [u for u in urls if ".mp4" in u]
        movies.append({"name": m.get("name") or "", "thumb": m.get("thumbnail") or "",
                       # mp4 があればそれ（Xにそのまま上げられる）。無ければほかの形の住所
                       "mp4": (sorted(mp4, key=lambda u: ("max" not in u, u))[0] if mp4 else ""),
                       "other": "" if mp4 else (urls[0] if urls else "")})
    return {"appid": appid,
            "name": d.get("name") or "",
            "store": f"https://store.steampowered.com/app/{appid}/",
            "header": d.get("header_image") or "",
            "capsule": d.get("capsule_imagev5") or d.get("capsule_image") or "",
            "short": d.get("short_description") or "",
            "website": d.get("website") or "",
            "developers": d.get("developers") or [],
            "release": (d.get("release_date") or {}).get("date") or "",
            "screenshots": shots, "movies": movies,
            "公式X": official_x(appid, d),
            "取得日": datetime.now(JST).strftime("%Y-%m-%d")}, None


def targets(data, leads):
    """(ゲーム名, どこに出ていたか) の並び。急上昇 → 新作ウォッチ → 順位表の順。"""
    out, seen = [], set()

    def add(name, where):
        if name and name not in seen:
            seen.add(name)
            out.append((name, where))
    for r in data.get("rising") or []:
        add(r.get("game"), "急上昇")
    for r in (leads.get("新作ウォッチ") or {}).get("発売後", []) + \
            (leads.get("新作ウォッチ") or {}).get("発売前", []):
        add(r.get("game"), "新作ウォッチ")
    for r in (data.get("ranking") or [])[:15]:
        add(r.get("game"), "順位表")
    return out[:MAX_GAMES]


def collect(ids, search_appid, get_json, stop_exc):
    """steam_reviews.py の最後に呼ばれる。ids は appid の台帳（書き足してよい）。"""
    data = read_json(SITE / "data.json", {}) or {}
    leads = read_json(SITE / "leads.json", {}) or {}
    got = read_json(OUT, {}) or {}
    got.pop("_説明", None)
    limit = (datetime.now(JST) - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%d")
    got = {k: v for k, v in got.items() if str(v.get("取得日", "")) >= limit}
    today = datetime.now(JST).strftime("%Y-%m-%d")
    order, looked = [], 0
    for name, where in targets(data, leads):
        appid = ids.get(name)
        if name not in ids and looked < 8:
            looked += 1
            appid, why = search_appid(name)
            if appid:
                ids[name] = appid
            elif why == "なし":
                ids[name] = None
            time.sleep(1.2)
        if not isinstance(appid, int):
            continue
        order.append((name, where))
        if got.get(name, {}).get("取得日") == today:
            continue                      # 今日もう取った（1日2回の更新の2回目）
        try:
            rec, why = fetch(appid, get_json)
        except stop_exc as ex:
            log(f"  画像の候補: {ex}。今回はここでやめます")
            break
        if rec:
            got[name] = rec
        else:
            log(f"  画像の候補 {name} … 取れませんでした（{why}）")
        time.sleep(1.2)
    write_json(OUT, dict({"_説明": "紹介ツイートに使う公式の画像・動画の住所（Steamのストア）。"
                                  "scripts/steam_media.py が毎日書く。画像そのものは持たない。"},
                         **dict(sorted(got.items()))))
    write_page(order, got)
    log(f"画像の候補: {sum(1 for n, _ in order if n in got)} ゲームぶん → site/admin/media.html")


CSS = """
:root{--bg:#F3F5F4;--card:#FFF;--line:#DBE4E2;--ink:#111B1D;--ink3:#5F7678;--acc:#0B6B70;--hot:#B4551C}
@media (prefers-color-scheme:dark){:root{--bg:#0E1718;--card:#152122;--line:#24383A;--ink:#EAF2F1;
 --ink3:#8FA7A8;--acc:#4FB3B8;--hot:#E8975C}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
 font-family:system-ui,"Hiragino Sans","Noto Sans JP",sans-serif;padding:16px;line-height:1.6}
h1{font-size:20px;margin:4px 0 6px}.lead{font-size:13px;color:var(--ink3);margin:0 0 14px;max-width:760px}
nav{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 16px}nav a{font-size:12px;color:var(--acc);
 border:1px solid var(--line);border-radius:99px;padding:3px 10px;text-decoration:none;background:var(--card)}
section{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px;margin:0 0 14px}
h2{font-size:17px;margin:0 0 4px}.meta{font-size:12px;color:var(--ink3);margin:0 0 8px}
.meta b{color:var(--hot)}.meta a{color:var(--acc)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:8px}
.grid a{display:block;position:relative}.grid img{width:100%;aspect-ratio:16/9;object-fit:cover;
 border-radius:6px;display:block;background:var(--line)}
.grid .n{position:absolute;left:4px;top:4px;font-size:11px;font-weight:700;background:rgba(0,0,0,.6);
 color:#fff;border-radius:4px;padding:0 5px}
.mv{font-size:12px;margin:8px 0 0}.mv a{color:var(--acc)}
.only{display:none;font-size:13px;margin:0 0 12px}.only a{color:var(--acc)}
body.one .only{display:block}body.one nav,body.one .lead{display:none}
body.one section{display:none}body.one section.on{display:block}
"""

# 住所に #app1234567 が付いていたら、そのゲームだけを見せる（2026-11-21）。
# ほかのゲームの画像を読み込まないので、スマホでも軽い。「ほかのゲームも見る」で全部に戻る
JS = """
(function(){
 function show(){var h=location.hash.slice(1),s=h&&document.getElementById(h);
  document.querySelectorAll('section.on').forEach(function(x){x.classList.remove('on')});
  if(s&&s.tagName==='SECTION'){s.classList.add('on');document.body.classList.add('one');
   s.querySelectorAll('img[loading=lazy]').forEach(function(i){i.loading='eager'});scrollTo(0,0)}
  else{document.body.classList.remove('one')}}
 addEventListener('hashchange',show);show();
})();
"""


def write_page(order, got):
    secs, nav = [], []
    for i, (name, where) in enumerate(order, 1):
        m = got.get(name)
        if not m:
            continue
        # ★住所の # は appid で固定する（2026-11-21）。朝の窓が
        #   https://hayarige.com/admin/media.html#app1234567 の形でリンクを渡すと、
        #   押してすぐそのゲームだけが開く。順番の番号（g1, g2…）だと毎回変わってしまう
        aid = f"app{m.get('appid')}" if m.get("appid") else f"g{i}"
        nav.append(f'<a href="#{aid}">{e(name)}</a>')
        imgs = [("ヘッダー", m.get("header"), m.get("header"))] + \
               [(str(k), s.get("thumb"), s.get("full"))
                for k, s in enumerate(m.get("screenshots") or [], 1)]
        grid = "".join(f'<a href="{e(full)}" target="_blank" rel="noopener">'
                       f'<img src="{e(th)}" alt="" loading="lazy"><span class="n">{e(lab)}</span></a>'
                       for lab, th, full in imgs if th and full)
        mv = "".join(
            f'<div class="mv">🎬 {e(x.get("name") or "トレーラー")} … '
            + (f'<a href="{e(x["mp4"])}" target="_blank" rel="noopener">mp4（そのまま保存できる）</a>'
               if x.get("mp4") else
               (f'<a href="{e(x["other"])}" target="_blank" rel="noopener">動画（mp4ではない形）</a>'
                if x.get("other") else "住所なし"))
            + "</div>" for x in (m.get("movies") or []))
        dev = "・".join(m.get("developers") or [])
        site = (f' ／ <a href="{e(m["website"])}" target="_blank" rel="noopener">公式サイト</a>'
                if m.get("website") else "")
        xs = m.get("公式X") or []
        xline = ('<p class="meta">公式X: ' + "、".join(
            f'<a href="https://x.com/{e(x["handle"])}" target="_blank" rel="noopener">@{e(x["handle"])}</a>'
            f'（{e(x.get("どこから"))}）' for x in xs) + "</p>") if xs else \
            '<p class="meta">公式X: Steamと公式サイトには見当たりませんでした</p>'

        secs.append(
            f'<section id="{aid}"><h2>{e(name)}</h2>'
            f'<p class="meta"><b>{e(where)}</b> ／ {e(dev)} ／ {e(m.get("release"))} ／ '
            f'<a href="{e(m["store"])}" target="_blank" rel="noopener">Steamのページ</a>{site}'
            f'（{e(m.get("取得日"))}に取得）</p>{xline}'
            f'<div class="grid">{grid}</div>{mv}</section>')
    body = ("<h1>紹介ツイートの画像・動画の候補</h1>"
            '<p class="only"><a href="#">← ほかのゲームも見る</a></p>'
            '<p class="lead">Steamのストアに公式が載せているスクリーンショットとトレーラーです。'
            "画像を押すと大きいサイズが開くので、長押しで保存してください。"
            "このページは画像の写しを持たず、Steamの住所をそのまま表示しています。"
            "使うときは、ゲーム名・公式の@・ストアのリンクを添えて、紹介として使ってください。"
            "プレスキットに利用条件があるゲームは、その条件に従ってください。"
            "（検索結果には出しません）</p>"
            f"<nav>{''.join(nav)}</nav>{''.join(secs) or '<p>今日はまだ候補がありません。</p>'}")
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(
        '<!doctype html><html lang="ja"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="robots" content="noindex,nofollow">'
        '<meta name="referrer" content="no-referrer">'
        f"<title>画像の候補 ｜ ハヤリゲー管理用</title><style>{CSS}</style></head>"
        f"<body>{body}<script>{JS}</script></body></html>\n", encoding="utf-8")
