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
import time
from datetime import datetime, timedelta

from common import DATA, SITE, JST, log, read_json, write_json

OUT = DATA / "steam_media.json"
PAGE = SITE / "admin" / "media.html"
SHOTS = 8           # 1ゲームあたり、残すスクリーンショットの数
KEEP_DAYS = 14      # 何日前に取ったものまで残すか
MAX_GAMES = 24      # 1回で見に行くゲームの数の上限（1.2秒ずつ空ける）


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
"""


def write_page(order, got):
    secs, nav = [], []
    for i, (name, where) in enumerate(order, 1):
        m = got.get(name)
        if not m:
            continue
        aid = f"g{i}"
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
        secs.append(
            f'<section id="{aid}"><h2>{e(name)}</h2>'
            f'<p class="meta"><b>{e(where)}</b> ／ {e(dev)} ／ {e(m.get("release"))} ／ '
            f'<a href="{e(m["store"])}" target="_blank" rel="noopener">Steamのページ</a>{site}'
            f'（{e(m.get("取得日"))}に取得）</p>'
            f'<div class="grid">{grid}</div>{mv}</section>')
    body = ("<h1>紹介ツイートの画像・動画の候補</h1>"
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
        f"<body>{body}</body></html>\n", encoding="utf-8")
