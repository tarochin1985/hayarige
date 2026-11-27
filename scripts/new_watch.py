#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""新作ウォッチ（/new/）。発売したての新作だけのランキング（2026-11-19）。

なぜ作ったか
------------
> 現在のランキングは常連の定番ゲームが多いので、新作のみにすることで
> 小粒なインディーゲームなども大量に拾えるようになり、むしろ「発掘」という
> 意味ではそちらのほうが意味のあるリストになるかもしれない。
> 僕も毎日見たくなるのはむしろそっちのランキングかも（2026-11-19 たろちんさん）

ふだんのランキングは Apex・マイクラ・スト6 が毎日上にいる。
ここでは**発売から NEW_DAYS 日以内**のゲームだけを、今日の配信チャンネル数で並べる。
発売前（体験版・β・先行プレイ）で配信されているものは、下に別に並べる。

「新作」をどう決めるか
----------------------
**発売日が分かっているものだけ**を載せる。分からないものは載せない
（古いゲームを新作として並べるのが、いちばんまずい間違いなので）。

  1. data/release_dates.json … 手で確かめた発売日（Steamのストアページなど）。
     辞書の直し（fix_dict.py の「発売日」）で足す。**こちらが優先**
  2. data/igdb_recent.json の "d" … IGDBの発売日（毎日の更新で取り直している。
     2026-11-19 に "d" を持たせ始めた。直近180日・先120日ぶん）

★IGDBの日付は「世界でいちばん早い発売日」。日本だけ遅れて出たゲームは、
  実際より古く見える（載らないことがある）。気づいたら 1. に書けば直る。
"""
import html
from datetime import date, timedelta

from common import DATA, read_json

NEW_DAYS = 60        # 発売から何日を「新作」とするか
LIST_MAX = 60        # 何本まで並べるか
SOON_MAX = 20        # 発売前のほうは何本まで


def e(s):
    return html.escape(str(s if s is not None else ""), quote=True)


def release_dates():
    """{名前: "YYYY-MM-DD" または "未発売"}。名前は正式名・表示名のどちらでも引ける。"""
    out = {}
    for r in read_json(DATA / "igdb_recent.json", []) or []:
        if r.get("d"):
            out[r["name"]] = r["d"]
    man = read_json(DATA / "release_dates.json", {}) or {}
    for k, v in man.items():
        if not str(k).startswith("_") and v:
            out[k] = str(v)
    return out


def _spark(vals):
    """7日の推移の小さい線。値が全部0なら出さない。"""
    vs = [float(v or 0) for v in (vals or [])]
    if len(vs) < 2 or max(vs) <= 0:
        return ""
    w, h, top = 64, 18, max(vs)
    pts = " ".join(f"{i * w / (len(vs) - 1):.1f},{h - 2 - (v / top) * (h - 4):.1f}"
                   for i, v in enumerate(vs))
    return (f'<svg class="nw-sp" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
            f'role="img" aria-label="直近7日の配信本数の推移">'
            f'<polyline points="{pts}" fill="none" stroke="currentColor" '
            f'stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/></svg>')


def pick(rows, today_str, first_seen=None):
    """(発売後の新作, 発売前) の2つのリスト。どちらも今日のチャンネル数の多い順。"""
    rd = release_dates()
    t = date.fromisoformat(today_str)
    new, soon = [], []
    for r in rows or []:
        if (r.get("channels") or 0) < 1:
            continue
        d = rd.get(r.get("canonical") or "") or rd.get(r.get("game") or "")
        if not d:
            continue
        item = dict(r)
        item["_first"] = (first_seen or {}).get(r.get("game"))
        if d == "未発売":
            item["_rel"], item["_ago"] = None, None
            soon.append(item)
            continue
        try:
            rdte = date.fromisoformat(d[:10])
        except ValueError:
            continue
        ago = (t - rdte).days
        item["_rel"], item["_ago"] = rdte, ago
        if ago < 0:
            soon.append(item)
        elif ago <= NEW_DAYS:
            new.append(item)
    key = lambda x: (-(x.get("channels") or 0), -(x.get("videos") or 0))  # noqa: E731
    new.sort(key=key)
    soon.sort(key=key)
    return new[:LIST_MAX], soon[:SOON_MAX]


def _row(i, r, home, slugs, kind, links=None):
    st = (r.get("streams") or [{}])[0]
    th = st.get("th") or ""
    img = (f'<img src="{e(th)}" alt="" loading="lazy">' if th
           else '<span class="ph"></span>')
    # ★サムネイルは元の配信へのリンクにし、下に引用元のチャンネルを出す（2026-11-27 たろちんさん）。
    #   > 新作ウォッチのページにもSteamやAmazonページへのリンクとサムネ引用元チャンネルへのリンクを
    #   > 出すようにしたほうがいいかと思った
    #   ほかのページ（コラム・ゲーム別ページ）は前から「YouTube ／ チャンネル名」を添えている
    if th and st.get("u"):
        img = f'<a href="{e(st["u"])}" target="_blank" rel="noopener">{img}</a>'
    src = ""
    if th and st.get("c"):
        ch = e(st["c"])
        if st.get("ci"):
            ch = (f'<a href="https://www.youtube.com/channel/{e(st["ci"])}" '
                  f'target="_blank" rel="noopener">{ch}</a>')
        src = f'<span class="nw-src">サムネイル: YouTube ／ {ch}</span>'
    # 店へのリンク。ゲーム別ページと同じ store_links（機種で出し分け。スマホ専用は出さない）
    shop = ""
    st_url, az_url = links(r) if links else (None, None)
    if st_url or az_url:
        shop = ('<span class="nw-buy">'
                + (f'<a class="st" href="{e(st_url)}" target="_blank" rel="noopener sponsored">Steamで探す</a>'
                   if st_url else "")
                + (f'<a class="az" href="{e(az_url)}" target="_blank" rel="noopener sponsored nofollow">Amazonで探す</a>'
                   if az_url else "")
                + "</span>")
    name = r.get("game") or ""
    sl = (slugs or {}).get(name)
    nm = (f'<a href="{home}g/{e(sl)}/">{e(name)}</a>' if sl else e(name))
    if kind == "new":
        ago = r["_ago"]
        # ★「発売3日目」とは書かない（2026-11-19）。11/16発売を11/19に「3日目」と出していた。
        #   数え方が人によって1日ずれる言い方なので、「発売から◯日」にそろえる
        when = "今日発売" if ago == 0 else f"発売から{ago}日"
        rel = f'{r["_rel"].month}月{r["_rel"].day}日発売'
        tag = f'<span class="nw-rel">{e(rel)}<b>{e(when)}</b></span>'
    else:
        if r.get("_rel"):
            rel = f'{r["_rel"].month}月{r["_rel"].day}日発売予定'
        else:
            rel = "発売日未定"
        tag = f'<span class="nw-rel soon">{e(rel)}</span>'
    first = r.get("_first")
    seen = (f'<span class="nw-seen">当サイトで初めて見つけた日 '
            f'{int(first[5:7])}月{int(first[8:10])}日</span>') if first else ""
    return (f'<li class="nw-i"><span class="nw-n">{i}</span>'
            f'<span class="nw-th">{img}</span>'
            f'<span class="nw-b"><span class="nw-g">{nm}</span>{tag}{seen}{src}{shop}</span>'
            f'<span class="nw-num"><b>{r.get("channels", 0)}</b><small>チャンネル</small>'
            f'<span class="nw-v">{r.get("videos", 0)}本</span>{_spark(r.get("spark"))}</span></li>')


CSS = """<style>
.nw-l{list-style:none;margin:10px 0 22px;padding:0;display:flex;flex-direction:column;gap:8px}
.nw-i{display:grid;grid-template-columns:28px 96px minmax(0,1fr) auto;gap:12px;align-items:center;
 background:var(--card);border:1px solid var(--line);border-radius:var(--r,12px);padding:10px 14px}
.nw-n{font-family:"Roboto Mono",monospace;font-weight:700;color:var(--ink-3);text-align:right}
.nw-th img,.nw-th .ph{display:block;width:96px;aspect-ratio:16/9;object-fit:cover;border-radius:6px;
 background:var(--line)}
.nw-b{display:flex;flex-direction:column;gap:3px;min-width:0}
.nw-g{font-weight:800;line-height:1.35;overflow-wrap:anywhere}
.nw-g a{color:inherit}
.nw-rel{font-size:12.5px;color:var(--ink-3)}
.nw-rel b{margin-left:8px;color:var(--hot);font-weight:700}
.nw-rel.soon{color:var(--accent)}
.nw-seen{font-size:12px;color:var(--ink-3)}
.nw-src{font-size:11.5px;color:var(--ink-3);overflow-wrap:anywhere}
.nw-src a{color:inherit;text-decoration:underline;text-underline-offset:2px}
.nw-buy{display:flex;flex-wrap:wrap;gap:6px;margin-top:3px}
.nw-buy a{font-size:12px;font-weight:700;padding:2px 10px;border-radius:99px;border:1px solid var(--line);
 color:var(--accent);background:var(--card);text-decoration:none}
.nw-buy a.az{color:var(--hot)}
.nw-th a{display:block}
.nw-num{display:flex;flex-direction:column;align-items:flex-end;gap:1px;color:var(--accent);min-width:70px}
.nw-num b{font-family:"Roboto Mono",monospace;font-size:20px;line-height:1;color:var(--ink)}
.nw-num small{font-size:11px;color:var(--ink-3)}
.nw-v{font-size:11.5px;color:var(--ink-3)}
.nw-sp{margin-top:3px}
@media (max-width:560px){
 .nw-i{grid-template-columns:22px 72px minmax(0,1fr);padding:10px 12px;gap:10px}
 .nw-th img,.nw-th .ph{width:72px}
 .nw-num{grid-column:2 / -1;flex-direction:row;align-items:baseline;gap:8px;justify-content:flex-start}
}
</style>"""


def page_html(rows, today_str, home, slugs, first_seen=None, range_label="", links=None):
    new, soon = pick(rows, today_str, first_seen)
    out = [CSS, "<h2>新作ウォッチ</h2>",
           '<p class="lead">発売から<b>' + str(NEW_DAYS) + '日以内</b>の新作だけを、'
           f'{e(range_label or "今日")}に配信していたチャンネルの多い順に並べています。'
           "いつもの定番ゲームが入らないので、<b>まだ小さいインディーや、"
           "出たばかりのゲーム</b>が見つかります。</p>"]
    if new:
        out.append('<ol class="nw-l">')
        out += [_row(i, r, home, slugs, "new", links) for i, r in enumerate(new, 1)]
        out.append("</ol>")
    else:
        out.append('<p class="muted">いまは並べられる新作がありません。</p>')
    if soon:
        out.append("<h2>発売前に配信されているゲーム</h2>"
                   '<p class="lead">体験版・ベータ・先行プレイなどで、発売前から配信されているゲームです。</p>'
                   '<ol class="nw-l">')
        out += [_row(i, r, home, slugs, "soon", links) for i, r in enumerate(soon, 1)]
        out.append("</ol>")
    out.append('<p class="muted" style="font-size:12.5px">発売日は、手で確かめたもの（Steamのストアページなど）と、'
               "ゲームのデータベース IGDB のものを使っています。発売日が分からないゲームは載せていません。"
               "日本での発売が遅れたゲームは、実際より古く数えられることがあります。"
               "チャンネル数・本数は当サイトが配信タイトルから独自に集計したものです。"
               "店へのリンクは店の検索結果に飛びます（商品ページではありません）。</p>")
    return "".join(out), new, soon
