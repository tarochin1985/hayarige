#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""コラムの品質チェック。

このサイトで一番読まれる部分なので、機械で守れるところは機械で守る。
ここを通らなかったコラムは、サイトに出ない（その日はコラム無しになる）。
出さない日があるのは失敗ではない。書くことが無い日に無理に書くほうが失敗。

単体でも動く:  python scripts/check_column.py data/columns/2026-08-27.json
"""
import json
import re
import sys
from pathlib import Path

# 裏が取れていないことを、取れているように見せてしまう言い回し。
# 「〜という事実」だけを書くルールを、言葉のレベルで縛る。
HEDGE = [
    "と思われる", "と見られる", "とみられる", "だろう", "かもしれない",
    "のようだ", "らしい。", "considered", "推測", "おそらく", "うわさ", "噂",
    "話題を呼んで", "が話題", "注目を集めて", "盛り上がりを見せて",
    "人気が高まって", "とされる", "という声も", "ではないだろうか",
]

# 出典に使ってはいけない場所。まとめサイトは話題の当たりをつけるためだけに使い、
# 根拠には必ず一次ソース（公式・ゲームメディア・実際の配信）を当てる。
BAD_SOURCE = [
    "matome", "blog.livedoor", "2ch", "5ch", "openwork", "togetter",
    "hatenablog", "note.com/", "wikiwiki", "seesaa", "fc2", "ameblo",
    "search.yahoo.co.jp/realtime", "vtuber-matome", "vtubermatome",
]

MIN_BODY, MAX_BODY = 120, 480


def validate(col):
    """問題点のリストを返す。空なら合格。"""
    bad = []
    if not isinstance(col, dict):
        return ["JSONの形が違います（オブジェクトではありません）"]

    for k in ("game", "headline", "body"):
        if not str(col.get(k, "")).strip():
            bad.append(f"{k} が空です")

    body = str(col.get("body", ""))
    if body and not (MIN_BODY <= len(body) <= MAX_BODY):
        bad.append(f"本文が {len(body)} 字です（{MIN_BODY}〜{MAX_BODY} 字にしてください）")

    for w in HEDGE:
        if w in body or w in str(col.get("headline", "")):
            bad.append(f"推測を含む言い回しがあります: 「{w}」")

    buy = col.get("buy")
    if buy is not None:
        u = str((buy or {}).get("u", ""))
        if "amazon.co.jp" not in u and "store.steampowered.com" not in u:
            bad.append(f"buy のURLはAmazonかSteamの商品ページにしてください: {u!r}")
        elif "amazon.co.jp/s?" in u or "/s?k=" in u:
            bad.append("buy に検索結果のURLは使えません。商品ページ（/dp/...）を指定してください")

    # summary（3行要約）はツイート画像に使う。無くてもよいが、
    # 入れるなら短く。長い行は画像の中で読めない。
    sm = col.get("summary")
    if sm is not None:
        if not isinstance(sm, list) or len(sm) > 3:
            bad.append("summary は3行までのリストにしてください")
        else:
            for i, line in enumerate(sm, 1):
                n = len(str(line))
                if n < 8 or n > 42:
                    bad.append(f"summary の{i}行目が {n} 字です（8〜42字にしてください）")

    srcs = col.get("sources") or []
    if not srcs:
        bad.append("出典がありません。一次ソースを最低1つ付けてください")
    for s in srcs:
        u = str((s or {}).get("u", ""))
        if not re.match(r"^https?://", u):
            bad.append(f"出典のURLが不正です: {u!r}")
            continue
        for ng in BAD_SOURCE:
            if ng in u.lower():
                bad.append(f"まとめ・二次情報を出典にしています: {u}")
                break
    return bad


def load_valid(path, log=print):
    """検証を通ったコラムだけを返す。通らなければ None。"""
    p = Path(path)
    if not p.exists():
        return None
    try:
        col = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        log(f"コラムのJSONが壊れています（{p.name}）: {e}")
        return None
    bad = validate(col)
    if bad:
        log(f"コラムを掲載しません（{p.name}）。理由:")
        for b in bad:
            log(f"  - {b}")
        return None
    return col


def main():
    if len(sys.argv) < 2:
        print("使い方: python scripts/check_column.py <コラムのJSON>")
        return 2
    ok = True
    for arg in sys.argv[1:]:
        bad = validate(json.loads(Path(arg).read_text(encoding="utf-8")))
        if bad:
            ok = False
            print(f"❌ {arg}")
            for b in bad:
                print(f"   - {b}")
        else:
            print(f"✅ {arg}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
