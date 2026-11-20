#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""答え合わせの候補を探す（2026-11-19）。

    python3 scripts/answer_check.py              # 今日の候補
    python3 scripts/answer_check.py --all        # 過去の全期間で、条件を満たした回を全部
    python3 scripts/answer_check.py --day 2026-10-15

なぜ作ったか
------------
> 答え合わせ投稿はツイート単独の施策としてよい。どの窓がそれを判断するか、
> 投稿する基準はどのくらいか、というのがポイントになるかも。
> （2026-11-19 たろちんさん）

「次に流行るゲームがわかるサイト」の看板を、いちばん直接に証明する投稿。
**ハヤリゲーが取り上げた日には小さかったゲームが、そのあと伸びた**ことを
数字で見せる。

★判断は**このスクリプト**がする。朝の窓は、ここが出した候補から投稿文を書くだけ。
  日付と数字を毎回同じ物差しで出せるので、「裏取りできないことを書かない」に合う。

条件（変えるときは、たろちんさんに確認する）
--------------------------------------------
1. **取り上げた日** … 次のどれか。
     ・毎日のコラムの主役（`"枠": "推し"` の日も含む。推しの日はそう書き添える）
     ・その日の急上昇の上位3つ（archive_index.json の hot）
     ・「次に流行るかもしれないゲーム」として紹介ツイートした日（data/紹介ツイート.json）
2. 取り上げた日の配信チャンネル数が **10 未満**（もう大きかったものは答え合わせにならない）
3. 取り上げた日の **3〜21日後** のどこかで、
     ・配信チャンネル数が **8 以上**
     ・その日の配信全体に占める割合が、取り上げた日の **3倍以上**
4. 1つのゲームにつき1回だけ（いちばん早く取り上げた日で数える）

★**割合で比べる理由。** 毎日見に行くチャンネルを 2026-11-11 に 2,000→全件、
  11-17 から毎日探索で増やしている。数をそのまま比べると、最近のゲームほど
  伸びて見えてしまう。その日に配信していたチャンネル全体（archive_index.json の
  channels）で割ってから比べる。

★**候補に出るのは、条件を初めて満たした日だけ**（と、その翌日）。
  毎日の更新が2回あるので、朝の窓が1回見落としても翌朝に拾える。
  それより後は出ない（同じ答え合わせを何度も投稿しないため）。

★大作の発売（リメイク・人気シリーズの新作）で伸びたのは、当たり前なので出さない
  ほうがよい。**これは機械では分からない**ので、朝の窓が判断する（手順に書いてある）。
"""
import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATA, read_json, today  # noqa: E402

PICK_MAX_CH = 10      # 取り上げた日にこれ以上いたら、もう大きかったので対象外
PEAK_MIN_CH = 8       # 伸びた日に、少なくともこれだけ配信していること
                      # （10だと小さいインディーが全部落ちた。How to Fish 2→8・Bombanana! 2→8。
                      #   2026-11-19 に過去の全期間で試して8にした）
SHARE_X = 3.0         # 割合で何倍になったら「伸びた」とするか
DAYS_FROM, DAYS_TO = 3, 21
SHOW_DAYS = 2         # 条件を初めて満たした日から何日、候補に出すか（当日＋翌日）


def _d(s):
    return date.fromisoformat(s)


def _names():
    """表示名 ⇔ 辞書のキー。記録と配信の名前が片方だけ変わった日のため。"""
    dn = read_json(DATA / "display_names.json", {}) or {}
    return dn, {v: k for k, v in dn.items()}


def _channels(gd, day, game, dn, inv):
    row = gd.get(day) or {}
    for k in (game, dn.get(game), inv.get(game)):
        if k and k in row:
            v = row[k]
            return int(v[1] if isinstance(v, (list, tuple)) else v)
    return 0


def picks():
    """ハヤリゲーが取り上げた日。{ゲーム: (日付, 種類)} のいちばん早いもの。"""
    out = {}

    def put(game, day, kind):
        game = str(game or "").strip()
        if not game or len(day) != 10:
            return
        if game not in out or day < out[game][0]:
            out[game] = (day, kind)
        elif day == out[game][0] and kind in ("コラム", "推し"):
            out[game] = (day, kind)          # 同じ日ならコラムのほうを名乗る

    for f in sorted((DATA / "columns").glob("20??-??-??.json")):
        try:
            c = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        kind = "推し" if str(c.get("枠") or "") == "推し" else "コラム"
        put(c.get("game"), f.stem, kind)
    for en in read_json(DATA / "archive_index.json", []) or []:
        for h in en.get("hot") or []:
            put(h.get("game"), str(en.get("date") or ""), "急上昇")
    # 紹介ツイート（2026-11-19〜）。「次に流行るかもしれないゲーム」として
    # たろちんさんがXに投稿したもの。朝の窓が data/紹介ツイート.json に書き残す。
    intro = read_json(DATA / "紹介ツイート.json", {}) or {}
    for day, games in intro.items():
        if str(day).startswith("_"):
            continue
        for g in games or []:
            put(g, str(day), "紹介ツイート")
    return out


def find(day=None, everything=False):
    """day の時点で出すべき候補のリスト。everything=True なら全期間ぶん。"""
    day = day or today()
    gd = read_json(DATA / "game_days.json", {}) or {}
    tot = {str(e.get("date")): int(e.get("channels") or 0)
           for e in (read_json(DATA / "archive_index.json", []) or [])}
    dn, inv = _names()
    days = sorted(d for d in gd if d <= day)
    out = []
    for game, (d0, kind) in sorted(picks().items(), key=lambda x: x[1][0]):
        if d0 > day:
            continue
        c0 = _channels(gd, d0, game, dn, inv)
        t0 = tot.get(d0) or 0
        if c0 >= PICK_MAX_CH or not t0:
            continue
        s0 = max(c0, 1) / t0           # 0チャンネル（記録が2ch未満）の日は1として数える
        hit = None
        for d in days:
            gap = (_d(d) - _d(d0)).days
            if gap < DAYS_FROM:
                continue
            if gap > DAYS_TO:
                break
            c = _channels(gd, d, game, dn, inv)
            t = tot.get(d) or 0
            if c >= PEAK_MIN_CH and t and (c / t) >= SHARE_X * s0:
                hit = (d, c, t, gap)
                break
        if not hit:
            continue
        d1, c1, t1, gap = hit
        if not everything and not (0 <= (_d(day) - _d(d1)).days < SHOW_DAYS):
            continue
        # 伸びたあとの山（今日までの最大）も添える。投稿文で「いまは」と書くときに使う
        peak = max(((d, _channels(gd, d, game, dn, inv)) for d in days if d >= d1),
                   key=lambda x: x[1], default=(d1, c1))
        out.append({
            "game": game,
            "取り上げた日": d0, "取り上げ方": kind,
            "その日のチャンネル数": c0, "その日の全体": t0,
            "伸びた日": d1, "何日後": gap,
            "伸びた日のチャンネル数": c1, "伸びた日の全体": t1,
            "割合で何倍": round((c1 / t1) / s0, 1),
            "今日までの山": {"日": peak[0], "チャンネル数": peak[1]},
            "ページ": f"/d/{d0}/" if kind != "急上昇" else f"/d/{d0}/",
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--day")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    res = find(a.day, a.all)
    if not res:
        print("答え合わせの候補はありません")
    for r in res:
        print(f"{r['game']}: {r['取り上げた日']}（{r['取り上げ方']}）に {r['その日のチャンネル数']}ch "
              f"→ {r['伸びた日']}（{r['何日後']}日後）に {r['伸びた日のチャンネル数']}ch"
              f"（割合で {r['割合で何倍']}倍）／山 {r['今日までの山']['日']} "
              f"{r['今日までの山']['チャンネル数']}ch")


if __name__ == "__main__":
    main()
