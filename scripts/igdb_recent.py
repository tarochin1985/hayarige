#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""発売直後・発売前のゲームだけを、毎日ちょっとずつ辞書に足す。

    python scripts/igdb_recent.py

なぜ必要か。

誤検出のいちばん多い原因は「新作が辞書に載っていない」ことだった。
辞書はIGDBのある時点のコピーなので、昨日出たゲームは入っていない。
そこに名前の一部が同じ古いゲームがいると、そちらに吸い込まれる。

    The Blood of Dawnwalker（9/3発売） → 1997年のFPS『Blood』
    Tales of Fear - Episode Zero      → 2005年のFPS『F.E.A.R.』
    Inferno Protocol                  → 『Protocol』

しかも困ったことに、この取り違えは<b>発売直後がいちばん多く起きる</b>。
みんなが一斉に配信するのがその時期だからで、いちばん数字が動く日に
いちばん間違えることになる。月1回の作り直しでは遅い。

かといって5万本の辞書を毎日作り直すと、8MBのファイルを毎日コミットする
ことになってリポジトリが太る。なので「最近出た／もうすぐ出る」ぶんだけを
小さな別ファイルにして、毎日足す。こちらは数百KBで、名前順に並べてあるので
日々の差分もごく小さい。

IGDBはTwitchのキーで認証する。YouTubeのクォータは1ポイントも使わない。
キーが無い環境では、何もせず正常終了する（毎日の更新を止めないため）。
"""
import os
import sys
import time
from datetime import datetime, timedelta, timezone

from common import DATA, log, read_json, write_json

PAST_DAYS = 180        # 何日前までの発売作を入れるか
FUTURE_DAYS = 120      # 何日先までの発売予定を入れるか（体験版・βが配信される）
PAGE = 500
CAP = 2500             # 過去・未来それぞれの上限

FIELDS = ("fields name,alternative_names.name,alternative_names.comment,"
          "first_release_date,total_rating_count,platforms,genres.name;")

PC_IDS = {6, 14, 3}
MOBILE_IDS = {39, 34}


def fetch(ig, where, sort):
    out, offset = [], 0
    while offset < CAP:
        body = f"{FIELDS} {where} {sort} limit {PAGE}; offset {offset};".encode()
        res = ig.query("games", body)
        if isinstance(res, dict) and "__error__" in res:
            log(f"  IGDBエラー（ここまでの分で続けます）: {res['__error__'][:160]}")
            break
        if not res:
            break
        out.extend(res)
        offset += PAGE
        time.sleep(0.28)          # 1秒4回までの制限を守る
    return out


def main():
    if not (os.environ.get("TWITCH_CLIENT_ID", "").strip()
            and os.environ.get("TWITCH_CLIENT_SECRET", "").strip()):
        log("Twitchのキーが無いので、新作の取り込みは飛ばします。")
        return 0

    from common import IGDB
    import igdb_sync as S

    ig = IGDB()
    now = datetime.now(timezone.utc)
    lo = int((now - timedelta(days=PAST_DAYS)).timestamp())
    hi = int((now + timedelta(days=FUTURE_DAYS)).timestamp())

    games = fetch(ig, f"where first_release_date > {lo} & first_release_date <= {int(now.timestamp())};",
                  "sort first_release_date desc;")
    log(f"最近{PAST_DAYS}日に出たゲーム: {len(games)} 本")
    up = fetch(ig, f"where first_release_date > {int(now.timestamp())} & first_release_date < {hi};",
               "sort first_release_date asc;")
    log(f"これから{FUTURE_DAYS}日以内に出るゲーム: {len(up)} 本")
    games += up

    out, seen = [], set()
    for g in games:
        name = (g.get("name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        alt = g.get("alternative_names") or []
        rec = {"name": name,
               "alias": [a.get("name", "").strip() for a in alt
                         if a.get("name", "").strip() and a.get("name") != name],
               "pop": g.get("total_rating_count", 0) or 0}
        jp = S.japanese_title(alt, name)
        if jp:
            rec["jp"] = jp
        pf = set(g.get("platforms") or [])
        tags = []
        if pf & PC_IDS:
            tags.append("pc")
        if pf - PC_IDS - MOBILE_IDS:
            tags.append("console")
        if tags:
            rec["p"] = tags
        gs = [x.get("name") for x in (g.get("genres") or []) if x.get("name")]
        if gs:
            rec["g"] = gs
        out.append(rec)

    # 名前順に固定して書く。順番が毎日変わると、中身が同じでも
    # 差分が巨大になってリポジトリが太る。
    out.sort(key=lambda r: r["name"])

    before = read_json(DATA / "igdb_recent.json", []) or []
    write_json(DATA / "igdb_recent.json", out)
    add = len({r["name"] for r in out} - {r["name"] for r in before})
    log(f"新作の辞書を更新しました: {len(out)} 本（前回から新しく {add} 本）"
        f" → data/igdb_recent.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
