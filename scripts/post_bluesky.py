#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""その日のコラムを Bluesky に自動で投稿する。

    python3 scripts/post_bluesky.py --dry-run   # 送る中身を見るだけ（鍵が無くても動く）
    python3 scripts/post_bluesky.py             # 本当に投稿する

投稿するもの
------------
文   … site/tweet.txt（Xに貼るものと同じ。make_card.py が書き出す）
画像 … site/card.png（同じく make_card.py が作る）

XとBlueskyで同じ文を使う。別々に書き分けると、片方だけ直したときに
食い違うし、そもそも「その日いちばん言いたいこと」は1つしかない。

鍵の置き場所
------------
GitHubの Settings → Secrets and variables → Actions に2つ登録する。
**このプログラムは環境変数からしか読まない。ファイルには絶対に書かない。**

  BLUESKY_HANDLE        … hayarige.com のようなハンドル（@は付けない）
  BLUESKY_APP_PASSWORD  … Blueskyの「アプリパスワード」

※ **本体のパスワードは使わないこと。** Blueskyには用途ごとに作って
  いつでも取り消せる「アプリパスワード」の仕組みがある。万一もれても
  そこだけ消せばよい。本体のパスワードを入れると、もれたとき
  アカウントごと乗っ取られる。

二重投稿をどう防ぐか
--------------------
「3. 毎日の更新」は1日2回動く。素朴に書くと同じ話を2回投稿してしまう。

そこで **コラムの日付**（site/data.json の column.date）を鍵にして、
投稿済みのものを data/bluesky_posted.json に残す。この記録は
ワークフローが git に積むので、次の回でも残っている。

コラムの日付を使うのがきもで、「今日の日付」ではない。今日のコラムが
まだ無い日は、サイトは前の日のコラムを出し続ける。今日の日付で数えると、
**同じコラムを日付だけ変えて何度も投稿してしまう。**
"""
import argparse
import json
import mimetypes
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DATA, SITE, log, read_json, write_json  # noqa: E402

HOST = "https://bsky.social"
BLOB_MAX = 1000000          # 画像の上限（1,000,000バイト）。Blueskyの仕様
POST_MAX = 300              # 本文の上限（書記素で300）
DONE = DATA / "bluesky_posted.json"
JST = timezone(timedelta(hours=9))

# タグの切れ目になる文字。全角の括弧やかぎかっこで終わらないと
# 「ハヤリゲー（9/30）🎮」まで丸ごとタグにしてしまう。
TAG_STOP = r"\s#＃…、。，．！？!?,.()（）\[\]【】「」『』〈〉《》〖〗｜|/／:：;；\"'“”"
TAG_RE = re.compile(rf"[#＃]([^{TAG_STOP}]{{1,64}})")
# URLに使える文字はASCIIだけ。ここを「空白以外」にすると、
# 「https://hayarige.com。つづき」の句点から先までURLに含めてしまう。
URL_RE = re.compile(r"https?://[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+")


def api(path, body=None, token=None, blob=None, ctype=None):
    """Blueskyのサーバーに1回話しかける。requests を入れずに済ませる。"""
    url = f"{HOST}/xrpc/{path}"
    if blob is not None:
        data, headers = blob, {"Content-Type": ctype or "application/octet-stream"}
    elif body is not None:
        data = json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json"}
    else:
        data, headers = None, {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        # 合言葉そのものは出さない。返ってきた説明文だけを出す
        raise RuntimeError(f"Blueskyが {e.code} を返しました: {detail}") from None


def facets(text):
    """本文の中のURLとタグに、押せる印を付ける。

    Blueskyは本文を見て勝手にリンクにはしてくれない。**何バイト目から
    何バイト目までがURLか**を、こちらが数えて渡す必要がある。
    ここで「文字数」を渡すと日本語の投稿がまるごとずれる（UTF-8では
    ひらがな1文字が3バイト）。必ずUTF-8にしてから数える。
    """
    out = []
    bs = lambda i: len(text[:i].encode("utf-8"))   # noqa: E731
    for m in URL_RE.finditer(text):
        uri = m.group(0).rstrip(".,;:!?")
        out.append({"index": {"byteStart": bs(m.start()),
                              "byteEnd": bs(m.start() + len(uri))},
                    "features": [{"$type": "app.bsky.richtext.facet#link",
                                  "uri": uri}]})
    for m in TAG_RE.finditer(text):
        out.append({"index": {"byteStart": bs(m.start()),
                              "byteEnd": bs(m.end())},
                    "features": [{"$type": "app.bsky.richtext.facet#tag",
                                  "tag": m.group(1)}]})
    out.sort(key=lambda f: f["index"]["byteStart"])
    return out


def alt_text(data):
    """画像の説明。目の見えない人にも中身が伝わるようにする。
    画像に書いてあることを、そのまま文にするだけでよい。"""
    col = data.get("column") or {}
    d = str(col.get("date") or data.get("date") or "")
    jp = f"{int(d[5:7])}月{int(d[8:10])}日" if len(d) >= 10 else ""
    rows = [r.get("game") for r in (data.get("ranking") or [])[:3] if r.get("game")]
    rising = (data.get("rising") or [{}])[0].get("game")
    parts = [f"ハヤリゲー{jp}のまとめ画像。"]
    if col.get("game"):
        parts.append(f"注目ゲームは『{col['game']}』。{col.get('headline', '')}。")
    if rows:
        parts.append("この日の上位は" + "、".join(rows) + "。")
    if rising:
        parts.append(f"いちばん伸びたのは『{rising}』。")
    return "".join(parts)[:1000]


def load_image():
    """カードの画像を読む。無い日や大きすぎる日は None を返して、文だけ投稿する。"""
    p = SITE / "card.png"
    if not p.is_file():
        log("site/card.png がありません。文だけ投稿します")
        return None, None
    raw = p.read_bytes()
    if len(raw) > BLOB_MAX:
        log(f"⚠️ 画像が大きすぎます（{len(raw):,}バイト／上限 {BLOB_MAX:,}）。"
            "文だけ投稿します")
        return None, None
    return raw, mimetypes.guess_type(p.name)[0] or "image/png"


def main():
    ap = argparse.ArgumentParser(description="その日のコラムをBlueskyに投稿する")
    ap.add_argument("--dry-run", action="store_true",
                    help="投稿せず、送る中身だけ見せる")
    ap.add_argument("--force", action="store_true",
                    help="投稿済みでももう一度投稿する（ふだんは使わない）")
    a = ap.parse_args()

    data = read_json(SITE / "data.json", None)
    if not isinstance(data, dict):
        log("site/data.json がありません。先に build_site.py を回してください")
        return 1
    col = data.get("column") or {}
    key = str(col.get("date") or "")
    if not key:
        log("コラムがまだありません。投稿しません")
        return 0

    done = read_json(DONE, {}) or {}
    if key in (done.get("投稿済み") or {}) and not a.force:
        log(f"{key} のコラムは投稿済みです（{done['投稿済み'][key]}）。何もしません")
        return 0

    text_path = SITE / "tweet.txt"
    if not text_path.is_file():
        log("site/tweet.txt がありません。先に make_card.py を回してください")
        return 1
    text = text_path.read_text(encoding="utf-8").strip()
    if len(text) > POST_MAX:
        log(f"⚠️ 本文が長すぎます（{len(text)}字／上限 {POST_MAX}）。投稿しません")
        return 1

    fac = facets(text)
    raw, ctype = load_image()
    alt = alt_text(data)

    log(f"コラムの日付: {key}")
    log("---- 本文 ----")
    log(text)
    log("--------------")
    log(f"押せる印: {len(fac)} 個 "
        + "／ ".join(f["features"][0]["$type"].split("#")[-1] for f in fac))
    log(f"画像: {'あり（' + format(len(raw), ',') + 'バイト）' if raw else 'なし'}")
    log(f"画像の説明: {alt[:60]}…")

    if a.dry_run:
        log("--dry-run なので、ここまでで終わります（投稿していません）")
        return 0

    handle = (os.environ.get("BLUESKY_HANDLE") or "").strip()
    pw = os.environ.get("BLUESKY_APP_PASSWORD") or ""
    if not handle:
        handle = (read_json(DATA / "site_config.json", {}) or {}).get(
            "bluesky_handle", "").strip()
    if not handle or not pw:
        log("BLUESKY_HANDLE と BLUESKY_APP_PASSWORD が入っていません。投稿しません。"
            "（GitHubの Settings → Secrets and variables → Actions で登録します）")
        return 0

    ses = api("com.atproto.server.createSession",
              {"identifier": handle, "password": pw})
    token, did = ses["accessJwt"], ses["did"]
    log(f"Blueskyにログインしました（{handle}）")

    embed = None
    if raw:
        blob = api("com.atproto.repo.uploadBlob", token=token, blob=raw, ctype=ctype)
        embed = {"$type": "app.bsky.embed.images",
                 "images": [{"alt": alt, "image": blob["blob"],
                             "aspectRatio": {"width": 1600, "height": 900}}]}

    record = {"$type": "app.bsky.feed.post", "text": text,
              "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
              "langs": ["ja"]}
    if fac:
        record["facets"] = fac
    if embed:
        record["embed"] = embed

    res = api("com.atproto.repo.createRecord",
              {"repo": did, "collection": "app.bsky.feed.post", "record": record},
              token=token)
    uri = res.get("uri", "")
    rkey = uri.rsplit("/", 1)[-1]
    link = f"https://bsky.app/profile/{handle}/post/{rkey}" if rkey else uri
    log(f"投稿しました: {link}")

    done.setdefault("_説明", "Blueskyに投稿済みのコラムの日付。"
                             "同じコラムを2回投稿しないために使います。"
                             "消すと、次の更新でもう一度投稿されます。")
    done.setdefault("投稿済み", {})[key] = link
    # 古いものは残しておいても意味がないので、直近60件だけ持つ
    keep = dict(sorted(done["投稿済み"].items())[-60:])
    done["投稿済み"] = keep
    write_json(DONE, done)
    return 0


if __name__ == "__main__":
    sys.exit(main())
