#!/usr/bin/env python3
"""Steamのレビューを拾って、コラムの窓に渡す材料に足す。

なぜ要るか（2026-11-08 たろちんさん）:

  > Steamレビューはかなり有益な情報かつユーザーの生の声が拾えるので一番よい。
  > **配信で流行っているという事実をハヤリゲーの仕組みで作り、どんなゲームで
  > どんな風に評価されているのか、はSteamレビューから拾う**のが一番いい
  > コラムになる気がする。

ハヤリゲーが数えられるのは「配信者が何本立てたか」まで。
**遊んだ人がどう思っているか**は、どこにも無かった。
配信タイトルは配信者の言葉であって、プレイヤー全体の感想ではない。

Steamのレビューは、

  ・**評価語と割合**（「非常に好評」「1,000件中87%が好評」）が一次ソースで出る
  ・**本文**が読める。これが「ユーザーの生の声」
  ・**APIキーも登録も要らない。YouTubeのクォータも1ユニットも使わない**

ので、ここだけで「ゲームがウケているのか」に答えが出る。

**失敗しても何も壊さない。** 通信が駄目でも、appidが分からなくても、
黙って前のまま置いて終わる（終了コードは必ず 0）。
ワークフロー側でも continue-on-error を付けてある。

走らせる順番:

    python scripts/build_site.py       ← 先。site/data.json と leads.json を作る
    python scripts/steam_reviews.py    ← あと。leads.json に "steam" を足す

appid の台帳は data/steam_ids.json。**手で直してよい。**
間違った appid が入っていたら、そこを書き換えれば次から直る。
`null` は「Steamには無いと確かめた」という意味で、二度と探しに行かない。
"""
import json
import re
import sys
import time
from urllib.parse import quote

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from common import DATA, SITE, log, read_json, write_json, http_json  # noqa: E402
import match as M  # noqa: E402

GAMES = 30          # 上位いくつまで見るか
NEW_PER_RUN = 12    # 1回の実行で、新しく appid を探しにいく数の上限
REVIEWS = 8         # 1ゲームあたり、残すレビュー本文の数
REVIEW_CHARS = 160  # レビュー本文を何字で切るか
UA = {"User-Agent": "hayarige-bot (+https://hayarige.com/)"}
LEDGER = DATA / "steam_ids.json"

LEDGER_NOTE = [
    "ゲーム名 → SteamのappID の台帳です。scripts/steam_reviews.py が使います。",
    "null は「Steamには無いと確かめた」という意味で、もう探しに行きません。",
    "\"?\" で始まる値は「名前が一致しなかったので保留」。人が見て直してください。",
    "**手で直してよいファイルです。** 間違ったappidを見つけたら書き換えれば次から直ります。",
    "判定（ランキング）には一切使いません。間違っていてもランキングは狂いません。",
]


def search_appid(name):
    """Steamのストア検索で appid を引く。見つからなければ None。

    **名前が一致しないものを黙って採らない。** 検索は何かしら返してくるので、
    詰めた字で突き合わせて、違えば保留にする（辞書の4-5章と同じ考え方）。
    """
    url = ("https://store.steampowered.com/api/storesearch/?term="
           + quote(name) + "&cc=jp&l=japanese")
    res = http_json(url, headers=UA, retries=2)
    if not isinstance(res, dict) or "__error__" in res:
        # ★通信の失敗を台帳に書かない。書くと「調べ済み」になって
        #   二度と探しに行かなくなる。次の回でやり直せるように、何も返さない。
        return None, None
    want = M.compact(name)
    for it in (res.get("items") or [])[:5]:
        if it.get("type") not in (None, "app", "game"):
            continue
        got = M.compact(it.get("name") or "")
        if got == want or got.startswith(want) or want.startswith(got):
            return int(it["id"]), None
    items = res.get("items") or []
    if not items:
        # Steamに1件も無い＝そのゲームはSteamで売っていない。
        # 「確かめた」として台帳に null を入れ、もう探しに行かない。
        return None, "なし"
    return None, "? 名前が合いません（Steam側は「%s」）" % (items[0].get("name") or "")


def fetch_reviews(appid):
    """レビューのまとめと、直近の本文を取る。取れなければ None。"""
    url = (f"https://store.steampowered.com/appreviews/{appid}?json=1"
           "&language=japanese&purchase_type=all&filter=recent"
           f"&num_per_page={REVIEWS}")
    res = http_json(url, headers=UA, retries=2)
    if not isinstance(res, dict) or res.get("success") != 1:
        return None
    q = res.get("query_summary") or {}
    pos, neg = int(q.get("total_positive") or 0), int(q.get("total_negative") or 0)
    tot = pos + neg
    out = {
        "appid": appid,
        "desc": q.get("review_score_desc") or "",
        "positive": pos, "negative": neg, "total": tot,
        "pct": round(100 * pos / tot) if tot else None,
        "recent": [],
    }
    for r in (res.get("reviews") or [])[:REVIEWS]:
        t = re.sub(r"\s+", " ", (r.get("review") or "")).strip()
        if not t:
            continue
        out["recent"].append({"up": bool(r.get("voted_up")),
                              "t": t[:REVIEW_CHARS]})
    return out


def main():
    data = read_json(SITE / "data.json", {}) or {}
    # ★急上昇を**先に**見る（2026-11-08）。
    #   毎日のコラムが書く相手は急上昇のほうで、しかも
    #   **30位の中に入っていないことのほうが多い。**
    #   2026-11-08は急上昇6件のうち5件が30位の外だった。
    #   順位表の30件も見るが、優先順位は急上昇が上。
    seen, rows = set(), []
    for r in list(data.get("rising") or []) + (data.get("ranking") or [])[:GAMES]:
        if r["game"] in seen:
            continue
        seen.add(r["game"])
        rows.append(r)
    if not rows:
        log("site/data.json にランキングがありません。先に build_site.py を走らせてください")
        return
    led = read_json(LEDGER, {}) or {}
    ids = led.get("id") or {}
    looked = 0
    out = {}
    for r in rows:
        name = r["game"]
        # PCで売っていないゲームは、そもそもSteamに無い。探しに行かない。
        # build_site が付けている steam（Steam内の検索リンク）が目印になる。
        if not r.get("steam"):
            continue
        if name not in ids:
            if looked >= NEW_PER_RUN:
                continue
            looked += 1
            appid, why = search_appid(r.get("canonical") or name)
            if appid is None and why is not None and (r.get("canonical") or name) != name:
                appid, why = search_appid(name)
            if appid:
                ids[name] = appid
            elif why == "なし":
                ids[name] = None          # Steamに無いと確かめた
            elif why:
                ids[name] = why           # "? 名前が合いません…"。人が直す
            else:
                log(f"  appid {name} … 通信できませんでした（次の回でやり直します）")
                time.sleep(1.2)
                continue
            log(f"  appid {name} → {ids[name]}")
            time.sleep(1.2)          # 続けて叩かない
        appid = ids.get(name)
        if not isinstance(appid, int):
            continue
        rev = fetch_reviews(appid)
        if rev:
            out[name] = rev
            log(f"  {name} … {rev['desc']}（{rev['pct']}% / {rev['total']}件）"
                f" 本文 {len(rev['recent'])}本")
        time.sleep(1.2)

    led = {"_説明": LEDGER_NOTE, "id": dict(sorted(ids.items()))}
    write_json(LEDGER, led)
    if not out:
        log("Steamのレビューは1件も取れませんでした。leads.json はそのままにします")
        return
    leads = read_json(SITE / "leads.json", {}) or {}
    leads["steam"] = out
    write_json(SITE / "leads.json", leads)
    log(f"Steamのレビューを {len(out)} ゲームぶん leads.json に入れました"
        f"（appidを新しく引いたのは {looked} 件）")


if __name__ == "__main__":
    try:
        main()
    except (Exception, SystemExit) as e:         # ここで必ず止める（SystemExit も）
        log(f"Steamのレビューは取れませんでした（続けます）: {type(e).__name__}: {str(e)[:200]}")
