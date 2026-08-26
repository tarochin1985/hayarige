#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""IGDBからゲーム名の辞書を作る。月に1回くらい動かせば十分。

日本語の別名（alternative_names）も一緒に取るのが肝心。
「バイオハザード」と「Resident Evil」が同じゲームだと分かるのはこの情報のおかげ。
"""
import time
from common import IGDB, DATA, log, write_json

# 上位から何本取るか。5万本もあれば配信されるゲームはほぼ網羅できる。
CAP = 50000
PAGE = 500

FIELDS = ("fields name,alternative_names.name,first_release_date,"
          "total_rating_count,category;")
# category=0 は本編のみ（DLCや移植版を除く）。version_parent=null は復刻版を除く。
WHERE = "where category = 0 & version_parent = null;"
SORT = "sort total_rating_count desc;"


def main():
    ig = IGDB()
    games, offset = [], 0
    while offset < CAP:
        body = f"{FIELDS} {WHERE} {SORT} limit {PAGE}; offset {offset};".encode()
        res = ig.query("games", body)
        if isinstance(res, dict) and "__error__" in res:
            log(f"IGDBエラー（ここまでの分で続行します）: {res['__error__'][:200]}")
            break
        if not res:
            break
        games.extend(res)
        offset += PAGE
        if offset % 5000 == 0:
            log(f"  {offset} 本まで取得")
        time.sleep(0.28)          # 1秒あたり4回までの制限を守る

    out = []
    for g in games:
        name = (g.get("name") or "").strip()
        if not name:
            continue
        alts = [a.get("name", "").strip()
                for a in (g.get("alternative_names") or [])]
        out.append({"name": name,
                    "alias": [a for a in alts if a and a != name],
                    "pop": g.get("total_rating_count", 0)})

    write_json(DATA / "igdb_games.json", out)
    log(f"IGDB辞書を作成しました: {len(out)} タイトル → data/igdb_games.json")


if __name__ == "__main__":
    main()
