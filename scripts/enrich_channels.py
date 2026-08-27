#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""チャンネル情報を集める。2番目に動かすもの。

やること：
  1. IDが分かっていないチャンネルを名前から探す
  2. 全チャンネルの登録者数・最終投稿日・ゲーム動画率を取得
  3. 目視確認用のCSVを書き出す

これが終われば、リストの選別が数字を見るだけで済むようになる。
"""
import csv, re
from datetime import datetime, timedelta
from common import (YouTube, QuotaExhausted, DATA, JST, log, die,
                    read_json, write_json, today, is_countable)
import match as M

CH_TSV = DATA / "channels.tsv"
OUT_JSON = DATA / "channels_enriched.json"
OUT_CSV = DATA / "channels_review.csv"
PROBE = 20                      # ゲーム率を見るために調べる直近動画の本数


EXTRA_TSV = DATA / "channels_extra.tsv"


def load_seed():
    """channels.tsv と channels_extra.tsv を読む。

    extra のほうは手で足したいチャンネル用。探索が channels.tsv に
    追記していくので、そちらを上書きせずに足せるようにしてある。
    handle 列（@なんとか）があれば、ID解決が1ポイントで済む。
    """
    rows, seen = [], set()
    for path in (CH_TSV, EXTRA_TSV):
        if not path.exists():
            continue
        with open(path, encoding="utf-8") as f:
            for r in csv.DictReader(f, delimiter="\t"):
                name = (r.get("name") or "").strip()
                cid = (r.get("channel_id") or "").strip()
                if not name or (cid and cid in seen):
                    continue
                if cid:
                    seen.add(cid)
                rows.append({"name": name, "channel_id": cid,
                             "handle": (r.get("handle") or "").strip().lstrip("@"),
                             "affiliation": (r.get("affiliation") or "").strip()})
    return rows


def dedupe(rows):
    """名前から解決した結果、同じチャンネルに行き着くことがあるので後からも重複を消す。"""
    out, seen = [], set()
    for r in rows:
        cid = r.get("channel_id")
        if cid and cid in seen:
            log(f"  重複のため除外: {r['name']}")
            continue
        if cid:
            seen.add(cid)
        out.append(r)
    return out


def handle_guess(name):
    """@ハンドルの当てずっぽう。当たれば1ユニットで済む（検索は100ユニット）。"""
    s = re.sub(r"[\s　/・。、！!？?（）()＆&]", "", name)
    return s if re.fullmatch(r"[A-Za-z0-9_.\-]{3,30}", s) else None


# 名前でわかる「配信チャンネルではないもの」
NOT_STREAMER = ("切り抜き", "きりぬき", "clips", "clip ")


def judge(rec, cutoff_day, min_subs):
    """このチャンネルを毎日見に行くかどうかの目安。

    以前はここを、実際に調べ直したチャンネルにしか適用していなかった。
    そのため前回の結果を使い回したチャンネルは判定が空のままになり、
    ゲームを配信していないチャンネルまで毎日見に行っていた。
    """
    st = str(rec.get("status") or "")
    if st:
        if "未調査" in st:
            return ""                      # まだ調べていないだけ。次回調べる
        # プレイリストが404など、そもそも取得できないチャンネル。
        # 空のままだと毎日見に行って毎日失敗するので、外しておく。
        return "外す（取得できず）"
    name = (rec.get("title") or rec.get("name") or "").lower()
    if any(w in name for w in NOT_STREAMER):
        return "外す（切り抜き）"
    if (rec.get("subscribers") or 0) < min_subs:
        return "外す（登録者が少ない）"
    lu = rec.get("last_upload") or ""
    if lu and lu < cutoff_day:
        return "外す（1年以上更新なし）"
    if (rec.get("long_videos") or 0) == 0:
        return "要確認（長尺動画なし）"
    if (rec.get("game_ratio") or 0) < 0.05:
        return "外す（ゲーム動画なし）"
    return "残す"


def main():
    yt = YouTube()
    seed = load_seed()
    prev = {c["channel_id"]: c for c in (read_json(OUT_JSON, []) or [])
            if c.get("channel_id")}
    log(f"チャンネル候補 {len(seed)} 件を読み込みました")

    # ---- 1. 足りないIDを埋める -------------------------------------------
    missing = [c for c in seed if not c["channel_id"]]
    log(f"IDが未取得のチャンネル: {len(missing)} 件")
    for c in missing:
        try:
            given = bool(c.get("handle"))
            h = c.get("handle") or handle_guess(c["name"])
            if h:
                r = yt.channels(handle=h)
                if r.get("items"):
                    c["channel_id"] = r["items"][0]["id"]
                    log(f"  ハンドルで解決: {c['name']}")
                    continue
            if given:
                # ハンドルを明示したのに見つからなかった場合、名前で検索し直さない。
                # 名前検索は1件目を無条件に採用するので、同名の切り抜きや別人を
                # 拾ってしまう。取り違えるくらいなら、登録しないほうがいい。
                log(f"  ハンドルが見つかりません（名前検索はしません）: "
                    f"{c['name']} @{c['handle']}")
                continue
            r = yt.search_channel(c["name"])
            items = r.get("items", [])
            if items:
                c["channel_id"] = items[0]["snippet"]["channelId"]
                c["resolved_as"] = items[0]["snippet"]["title"]
                log(f"  検索で解決: {c['name']} → {c['resolved_as']}")
            else:
                log(f"  見つかりません: {c['name']}")
        except QuotaExhausted as e:
            log(f"クォータ上限のため、ID解決をここで打ち切ります: {e}")
            break
        except Exception as e:
            log(f"  失敗 {c['name']}: {e}")

    targets = dedupe([c for c in seed if c["channel_id"]])
    log(f"ID確定 {len(targets)} 件 ／ 使用クォータ {yt.used}")

    # ---- 2. 基本情報をまとめて取得（50件ずつ・1ユニット） ------------------
    info = {}
    for i in range(0, len(targets), 50):
        chunk = [c["channel_id"] for c in targets[i:i + 50]]
        try:
            r = yt.channels(ids=chunk)
        except QuotaExhausted:
            log("クォータ上限のため基本情報の取得を打ち切ります")
            break
        for it in r.get("items", []):
            info[it["id"]] = it
    log(f"基本情報を取得: {len(info)} 件 ／ 使用クォータ {yt.used}")

    # ---- 3. 直近動画からゲーム率を測る（1チャンネル1〜2ユニット） -----------
    idx = M.build_index()
    if len(idx.exact) < 500:
        die("ゲーム名辞書がほとんど空です。ゲーム動画率を正しく測れません。",
            "『2. チャンネル情報を集める』を、"
            "『ゲーム辞書も作り直す』を yes にして実行し直してください。")
    cutoff_day = (datetime.now(JST) - timedelta(days=365)).strftime("%Y-%m-%d")
    cfg = read_json(DATA / "site_config.json", {}) or {}
    min_subs = int(cfg.get("min_subscribers") or 0)
    log(f"登録者数の下限: {min_subs:,} 人（data/site_config.json の min_subscribers）")
    out = []
    for n, c in enumerate(targets, 1):
        it = info.get(c["channel_id"])
        rec = dict(c)
        if not it:
            rec.update(status="情報取得できず")
            out.append(rec)
            continue
        rec["title"] = it["snippet"]["title"]
        rec["subscribers"] = int(it["statistics"].get("subscriberCount", 0) or 0)
        uploads = it["contentDetails"]["relatedPlaylists"].get("uploads")

        # 前回すでに調べていて、登録者数がほぼ同じなら再調査を省く
        p = prev.get(c["channel_id"])
        if p and p.get("long_videos") is not None and \
           abs(p.get("subscribers", 0) - rec["subscribers"]) < rec["subscribers"] * 0.02:
            rec.update(last_upload=p.get("last_upload"),
                       game_ratio=p.get("game_ratio"),
                       long_videos=p.get("long_videos"),
                       sample=p.get("sample"), status=p.get("status", ""))
            rec["auto"] = judge(rec, cutoff_day, min_subs)
            out.append(rec)
            continue

        try:
            pl = yt.uploads(uploads, PROBE) if uploads else {"items": []}
            vids = [x["contentDetails"]["videoId"] for x in pl.get("items", [])]
            if vids:
                vr = yt.videos(vids[:50])
                titles, latest = [], None
                for v in vr.get("items", []):
                    pub = v["snippet"]["publishedAt"]
                    latest = max(latest, pub) if latest else pub
                    dur = (v.get("contentDetails") or {}).get("duration", "")
                    # Shortsと切り抜きは「配信」ではないので率の計算から外す
                    if is_countable(v["snippet"]["title"], dur):
                        titles.append(v["snippet"]["title"])
                hit = sum(1 for t in titles if M.extract(t, idx, fallback=False)[0])
                rec["last_upload"] = (latest or "")[:10]
                rec["game_ratio"] = round(hit / len(titles), 2) if titles else 0.0
                rec["long_videos"] = len(titles)
                rec["sample"] = titles[0][:60] if titles else ""
            else:
                rec.update(last_upload="", game_ratio=0.0, sample="")
        except QuotaExhausted:
            log(f"クォータ上限のため {n} 件目で調査を打ち切ります")
            rec.update(status="未調査")
            out.append(rec)
            out += [dict(x, status="未調査") for x in targets[n:]]
            break
        except Exception as e:
            rec.update(status=f"エラー: {e}"[:80])

        rec["auto"] = judge(rec, cutoff_day, min_subs)
        out.append(rec)
        if n % 50 == 0:
            log(f"  {n}/{len(targets)} 件 ／ 使用クォータ {yt.used}")

    write_json(OUT_JSON, out)

    with open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["No.", "チャンネル名", "所属", "登録者数", "最終投稿日",
                    "ゲーム動画率", "自動判定", "あなたの判定", "チャンネルURL", "直近タイトル例"])
        for i, c in enumerate(sorted(out, key=lambda x: -(x.get("subscribers") or 0)), 1):
            w.writerow([i, c.get("title") or c["name"], c.get("affiliation", ""),
                        c.get("subscribers", ""), c.get("last_upload", ""),
                        c.get("game_ratio", ""), c.get("auto", c.get("status", "")), "",
                        f"https://www.youtube.com/channel/{c['channel_id']}"
                        if c.get("channel_id") else "",
                        c.get("sample", "")])

    keep = sum(1 for c in out if c.get("auto") == "残す")
    drop = sum(1 for c in out if str(c.get("auto", "")).startswith("外す"))
    check = sum(1 for c in out if c.get("auto") == "要確認")
    log("")
    log(f"完了。使用クォータ {yt.used} / {9000}")
    log(f"  自動で『残す』 : {keep} 件")
    log(f"  自動で『外す』 : {drop} 件")
    log(f"  目視が必要     : {check} 件  ← あなたが見るのはここだけです")
    log(f"→ data/channels_review.csv を確認してください")


if __name__ == "__main__":
    main()
