#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""共通処理：APIの呼び出し、クォータ管理、ファイルの読み書き。

このファイルは直接実行しません。他のスクリプトから読み込まれます。
"""
import json, os, re, sys, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib import request, parse, error

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SITE = ROOT / "site"
JST = timezone(timedelta(hours=9))

# YouTube APIの1日の無料枠。使い切る前に止めるための上限。
QUOTA_LIMIT = int(os.environ.get("QUOTA_LIMIT", "9000"))


def today() -> str:
    return datetime.now(JST).strftime("%Y-%m-%d")


def log(msg: str):
    print(f"[{datetime.now(JST).strftime('%H:%M:%S')}] {msg}", flush=True)


def die(msg: str, hint: str = ""):
    print("\n" + "=" * 60, flush=True)
    print(f"エラー: {msg}", flush=True)
    if hint:
        print(f"対処: {hint}", flush=True)
    print("=" * 60 + "\n", flush=True)
    sys.exit(1)


def iso_seconds(dur: str) -> int:
    """ISO8601の長さ（PT1H2M3S）を秒に直す。Shortsを見分けるのに使う。"""
    if not dur:
        return 0
    m = re.match(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", dur)
    if not m:
        return 0
    d, h, mi, sec = (int(x) if x else 0 for x in m.groups())
    return ((d * 24 + h) * 60 + mi) * 60 + sec


SKIP_WORDS = ("切り抜き", "#shorts", "＃shorts")


def is_countable(title: str, duration: str) -> bool:
    """配信・動画として数える対象か。Shortsと切り抜きは除く。"""
    if iso_seconds(duration) and iso_seconds(duration) <= 90:
        return False
    low = title.lower()
    return not any(w.lower() in low for w in SKIP_WORDS)


def read_json(path, default=None):
    p = Path(path)
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def write_json(path, obj):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def http_json(url, data=None, headers=None, method=None, retries=3):
    """JSONを取得する。混雑時は待って数回やり直す。"""
    headers = dict(headers or {})
    body = None
    if data is not None:
        body = data if isinstance(data, bytes) else data.encode("utf-8")
    req = request.Request(url, data=body, headers=headers, method=method)
    last = None
    for attempt in range(retries):
        try:
            with request.urlopen(req, timeout=45) as r:
                return json.loads(r.read().decode("utf-8"))
        except error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:600]
            last = f"HTTP {e.code}: {detail}"
            if e.code in (403, 400, 401):
                return {"__error__": last, "__status__": e.code}
            time.sleep(2 * (attempt + 1))
        except Exception as e:                       # 通信断など
            last = str(e)
            time.sleep(2 * (attempt + 1))
    return {"__error__": last or "unknown", "__status__": 0}


# ---------------------------------------------------------------- YouTube
class YouTube:
    """YouTube Data API の呼び出し。使ったクォータを数える。"""

    BASE = "https://www.googleapis.com/youtube/v3/"

    def __init__(self, key=None):
        self.key = key or os.environ.get("YOUTUBE_API_KEY", "").strip()
        if not self.key:
            die("YouTubeのAPIキーが見つかりません。",
                "GitHubの Settings → Secrets and variables → Actions に "
                "YOUTUBE_API_KEY という名前で登録されているか確認してください。")
        self.used = 0

    def call(self, endpoint, cost, **params):
        if self.used + cost > QUOTA_LIMIT:
            raise QuotaExhausted(f"1日の上限に近づいたため停止しました（使用 {self.used}）")
        params["key"] = self.key
        clean = {k: v for k, v in params.items() if v is not None}
        url = self.BASE + endpoint + "?" + parse.urlencode(clean)
        res = http_json(url)
        self.used += cost
        if "__error__" in res:
            msg = res["__error__"]
            if "quotaExceeded" in msg:
                raise QuotaExhausted("YouTube側のクォータを使い切りました")
            if "API key not valid" in msg or res.get("__status__") == 400:
                die("YouTubeのAPIキーが正しくないようです。",
                    "キーをコピーし直して、Secretsに登録し直してください。")
            if res.get("__status__") == 403:
                die("YouTube APIへのアクセスが拒否されました。",
                    "Google Cloudで『YouTube Data API v3』が有効になっているか、"
                    "キーの制限が正しいかを確認してください。\n詳細: " + msg[:300])
            raise RuntimeError(msg)
        return res

    def channels(self, ids=None, handle=None):
        """チャンネル情報。IDは50件まとめて1ユニット。"""
        if handle:
            return self.call("channels", 1, part="snippet,statistics,contentDetails",
                             forHandle=handle)
        return self.call("channels", 1, part="snippet,statistics,contentDetails",
                         id=",".join(ids), maxResults=50)

    def uploads(self, playlist_id, max_results=20):
        """アップロード一覧。1チャンネルにつき1ユニット。"""
        return self.call("playlistItems", 1, part="contentDetails",
                         playlistId=playlist_id, maxResults=max_results)

    def videos(self, ids):
        """動画の詳細。50件まとめて1ユニット。"""
        return self.call("videos", 1,
                         part="snippet,statistics,contentDetails,liveStreamingDetails",
                         id=",".join(ids), maxResults=50)

    def search_channel(self, q):
        """名前からチャンネルを探す。1回100ユニットと高いので最後の手段。"""
        return self.call("search", 100, part="snippet", type="channel", q=q, maxResults=3)


    def search_videos(self, q, published_after=None, order="viewCount", n=50):
        """キーワードで動画を探し、その配信者を見つけるために使う。1回100ユニット。"""
        kw = dict(part="snippet", type="video", q=q, maxResults=n,
                  regionCode="JP", relevanceLanguage="ja", order=order)
        if published_after:
            kw["publishedAfter"] = published_after
        return self.call("search", 100, **kw)


class QuotaExhausted(Exception):
    pass


# ---------------------------------------------------------------- IGDB
class IGDB:
    """ゲーム名辞書のもと。Twitchのアカウントで認証する。"""

    def __init__(self):
        cid = os.environ.get("TWITCH_CLIENT_ID", "").strip()
        sec = os.environ.get("TWITCH_CLIENT_SECRET", "").strip()
        if not cid or not sec:
            die("Twitchのキーが見つかりません。",
                "Secretsに TWITCH_CLIENT_ID と TWITCH_CLIENT_SECRET が"
                "登録されているか確認してください。")
        self.cid = cid
        tok = http_json(
            "https://id.twitch.tv/oauth2/token?" + parse.urlencode(
                {"client_id": cid, "client_secret": sec,
                 "grant_type": "client_credentials"}),
            data=b"", method="POST")
        if "__error__" in tok or "access_token" not in tok:
            die("Twitchの認証に失敗しました。",
                "Client ID と Client Secret を貼り直してください。"
                "Secretは一度しか表示されないため、控えを間違えている可能性があります。\n"
                "詳細: " + str(tok)[:300])
        self.token = tok["access_token"]

    def query(self, endpoint, body):
        return http_json(f"https://api.igdb.com/v4/{endpoint}", data=body,
                         headers={"Client-ID": self.cid,
                                  "Authorization": f"Bearer {self.token}",
                                  "Accept": "application/json"},
                         method="POST")
