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

# 記録ページの置き場所。「初めて」を確かめるのに使う。
SITE_D = Path(__file__).resolve().parent.parent / "site" / "d"

# 「当サイトの集計に入ったのは今日が初めて」と書いてよいのは、
# 本当に過去1日も出ていないときだけ。
# 2026-09-12に、直近3日ぶんしか見ずに How to Fish を「初めて」と書いて間違えた。
# 実際には 8/26・8/27・8/28・9/1・9/6 にも入っていた。
# 人が数え忘れる種類の間違いなので、機械で確かめる。
FIRST_RE = re.compile(
    r"(当サイト|集計|ランキング)[^。]{0,40}?(初めて|初登場|今回が初)"
    r"|(初めて|初登場|今回が初)[^。]{0,40}?(集計|ランキング)")


def _today():
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) + timedelta(hours=9)).strftime("%Y-%m-%d")


def seen_days(game, before):
    """そのゲームがランキングに入った日を古い順に返す（before より前だけ）。

    記録ページに埋め込んである当日ぶんのデータを読む。30日を過ぎた日でも
    ゲーム名と件数は残っているので、全期間を数えられる。
    """
    out = []
    if not game or not SITE_D.is_dir():
        return out
    for d in sorted(SITE_D.iterdir()):
        if not d.is_dir() or (before and d.name >= before):
            continue
        f = d / "index.html"
        if not f.is_file():
            continue
        try:
            h = f.read_text(encoding="utf-8")
            i = h.index("const DATA = ") + len("const DATA = ")
            obj, _ = json.JSONDecoder().raw_decode(h[i:])
        except (ValueError, OSError):
            continue
        if any(r.get("game") == game for r in (obj.get("ranking") or [])):
            out.append(d.name)
    return out

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


def style(col, day=""):
    """書き方の注意を返す。**これがあってもサイトには出す。**

    validate() のほうは「出してはいけない」ものだけを見ている（裏取り・出典・
    リンクの正しさ）。見出しの長さのような書き方の話でその日のコラムが
    まるごと消えるのは、直したい問題よりも大きな損になる。
    だから警告として分け、書いている最中に気づける形にしてある。
    """
    if not isinstance(col, dict):
        return []
    out = []
    # 見出しは短いキャッチコピー。説明の一文になっていると、
    # Xの画像で2〜3行を食いつぶして本文が小さくなる。
    head = str(col.get("headline", "")).strip()
    if head:
        if not (8 <= len(head) <= 30):
            out.append(f"見出しが {len(head)} 字です（8〜30字のキャッチコピーにしてください）")
        if head.endswith("。"):
            out.append("見出しが説明の一文になっています。句点で終わらない短い言葉にしてください")
        game = str(col.get("game", "")).strip()
        if game and game in head:
            out.append(f"見出しにゲーム名が入っています（「{game}」）。"
                       "見出しのすぐ上にゲーム名が大きく出るので、重ねないでください")

    # 「初めて」と書いているなら、本当に初めてかを数えて確かめる。
    # 書いていない日は記録ページを読みに行かないので、普段の負担はない。
    text = str(col.get("body", "")) + " " + str(col.get("headline", ""))
    if FIRST_RE.search(text):
        # day はコラムの日付（ファイル名から取る）。その日より前だけを数える。
        # ここを空にすると当日の記録ページまで数えてしまい、本当に初めての
        # ゲームを「前にも出ている」と誤って弾いてしまう。
        days = seen_days(str(col.get("game", "")).strip(),
                         day or str(col.get("date", "")) or _today())
        if days:
            # ここは「間違い」と断定しない。「昨日が初めて」のように、
            # 過去に出ていても正しい書き方があるため。事実だけを出して、
            # 書いた本人に確かめさせる。
            last = f"{int(days[-1][5:7])}月{int(days[-1][8:10])}日"
            first = f"{int(days[0][5:7])}月{int(days[0][8:10])}日"
            out.append(
                f"「初めて」と書いています。このゲームがランキングに入った日は"
                f"{first}が最初で、直近は{last}、全部で{len(days)}日あります。"
                "書いた内容と合っているか確かめてください"
                "（本当に今日が初めてなら、この行は出ません）")
    return out


def validate(col):
    """出してはいけない理由のリストを返す。空なら掲載してよい。"""
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
    for w in style(col, p.stem):
        log(f"コラムの書き方の注意（{p.name}）: {w}")
    return col


def main():
    if len(sys.argv) < 2:
        print("使い方: python scripts/check_column.py <コラムのJSON>")
        return 2
    ok = True
    for arg in sys.argv[1:]:
        col = json.loads(Path(arg).read_text(encoding="utf-8"))
        bad, warn = validate(col), style(col, Path(arg).stem)
        if bad or warn:
            ok = False
            print(("❌ " if bad else "⚠️  ") + arg)
            for b in bad:
                print(f"   - {b}")
            for w in warn:
                print(f"   ※ {w}（サイトには出ますが、直したほうがよいです）")
        else:
            print(f"✅ {arg}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
