#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""IGDBからゲーム名の辞書を作る。月に1回くらい動かせば十分。

日本語の別名（alternative_names）も一緒に取るのが肝心。
「バイオハザード」と「Resident Evil」が同じゲームだと分かるのはこの情報のおかげ。
"""
import re, time
from common import IGDB, DATA, log, die, write_json

# 上位から何本取るか。5万本もあれば配信されるゲームはほぼ網羅できる。
CAP = 50000
PAGE = 500

FIELDS = ("fields name,alternative_names.name,alternative_names.comment,"
          "first_release_date,total_rating_count,platforms;")

# 対応機種の判定に使うIGDBのID。
# PC・Mac・Linux・スマホ以外が入っていれば「据置/携帯ゲーム機で売っている」と見なす。
PC_IDS = {6, 14, 3}            # Windows / Mac / Linux
MOBILE_IDS = {39, 34}          # iOS / Android
SORT = "sort total_rating_count desc;"

# 本編だけに絞る条件。IGDBは項目名を変えることがあるので、
# 使えるものが見つかるまで順に試す。最後は絞り込みなし。
WHERE_CANDIDATES = [
    "where game_type = 0 & version_parent = null;",
    "where category = 0 & version_parent = null;",
    "where version_parent = null;",
    "",
]


def pick_where(ig):
    for w in WHERE_CANDIDATES:
        res = ig.query("games", f"{FIELDS} {w} {SORT} limit 1;".encode())
        if isinstance(res, list) and res:
            log(f"絞り込み条件: {w or '（なし）'}")
            return w
        if isinstance(res, dict) and "__error__" in res:
            log(f"  この条件は使えませんでした: {w}")
    return None


def main():
    ig = IGDB()
    where = pick_where(ig)
    if where is None:
        die("IGDBからゲーム一覧を取得できませんでした。",
            "しばらく待ってから再実行してください。続く場合は報告してください。")

    games, offset = [], 0
    while offset < CAP:
        body = f"{FIELDS} {where} {SORT} limit {PAGE}; offset {offset};".encode()
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

    KANA = re.compile(r"[ぁ-んァ-ヴー]")
    CJK = re.compile(r"[぀-ヿ一-鿿]")

    def japanese_title(alt_list, name):
        """日本語のタイトルを選ぶ。IGDBの注記に Japan とあるものを最優先。"""
        cands = []
        for a in alt_list:
            nm = (a.get("name") or "").strip()
            if not nm or nm == name or not CJK.search(nm):
                continue
            note = (a.get("comment") or "").lower()
            score = 0
            if "japan" in note:
                score += 10
            if KANA.search(nm):          # かなを含めば中国語ではない
                score += 5
            cands.append((score, len(nm), nm))
        cands = [c for c in cands if c[0] > 0]
        return max(cands)[2] if cands else None

    out = []
    for g in games:
        name = (g.get("name") or "").strip()
        if not name:
            continue
        alt_list = g.get("alternative_names") or []
        alts = [a.get("name", "").strip() for a in alt_list]
        rec = {"name": name,
               "alias": [a for a in alts if a and a != name],
               "pop": g.get("total_rating_count", 0)}
        jp = japanese_title(alt_list, name)
        if jp:
            rec["jp"] = jp
        # どの店へのリンクを出すかの判断材料。"p" は pc / console の組み合わせ。
        pf = set(g.get("platforms") or [])
        tags = []
        if pf & PC_IDS:
            tags.append("pc")
        if pf - PC_IDS - MOBILE_IDS:
            tags.append("console")
        if tags:
            rec["p"] = tags
        out.append(rec)

    write_json(DATA / "igdb_games.json", out)
    log(f"IGDB辞書を作成しました: {len(out)} タイトル → data/igdb_games.json")


if __name__ == "__main__":
    main()
