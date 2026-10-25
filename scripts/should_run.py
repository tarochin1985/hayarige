#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""定期実行を「走らせるか、何もせず終えるか」決める関所。

    python scripts/should_run.py          判断する（GitHub の出力に go=yes/no を書く）
    python scripts/should_run.py --mark   「いま取り込んだ」と記録する
    python scripts/should_run.py --test "2026-10-26T22:11:00Z"   判断だけ試す

なぜ要るか（2026-10-25 たろちんさん）
------------------------------------

    > githubの自動更新が最近数時間レベルでズレている。もう少しなんとかならないか。
    > クオータがもったいないので、気付いたときに手動更新をしたら
    > その後の半日くらい自動更新はスキップするような仕組みにできないか。

**実際にどれだけズレていたかを、コミットの時刻で数えた**（10-15〜10-25）。

    予定 22:00 UTC（日本時間 7:00）… 中央値 **134分おくれ** / 最大 156分
    予定 10:00 UTC（日本時間 19:00）… 中央値 **260分おくれ** / 最大 305分

朝の更新が日本時間9時すぎに終わっていた。**8時の朝のリマインドは、
その前の晩のデータを見ていたということ。** 夜の更新は23時すぎだった。

GitHubの定期実行は「混雑時に遅れることがある」と公式に書かれていて、
**いちばん混むのは毎時0分**。1日2回・どちらも0分に置いていたので、
まるごと行列の後ろに並んでいた。そこで2つ変えた。

  1. **0分を避けて、1つの枠に何回も声をかける**（3-daily.yml の cron）。
     日本時間 6:11〜8:41 と 18:11〜20:41 に、30分おきに6回ずつ。
     **先に届いたものが仕事をして、残りはこの関所で止まる。**
  2. **YouTubeのクォータを使う前に、ここで判断する。** 関所は別の仕事
     （job）なので、止まるときは1ポイントも使わない。

止める条件は2つだけ
-------------------

  ・**同じ枠でもう取り込んでいる** … 枠は「朝」（日本時間4:00〜15:59）と
    「夜」（16:00〜翌3:59）の2つ。手で回したぶんも同じ枠に数える。
    **これがたろちんさんの言っていた場面そのもの。** 朝の更新が遅れていて、
    気づいて手で回したあと、遅れて届いた定期実行が**もう一度取りに行く**のを止める
  ・**前の取り込みから6時間たっていない** … 枠をまたいでも近すぎるときの保険。
    まともな間隔はいちばん短くても9時間半（朝8:41→夜18:11）あるので、
    ふだんの更新をこれで止めてしまうことはない

**手で回したときは必ず走る。** 止めたいときに止められないと困るので。

★**壊れたときは「走る」側に倒す。** この関所が失敗したら更新が全部止まる、
というのがいちばん悪い。3-daily.yml 側の条件も `go == 'no'` のときだけ
止めるように書いてあり、ここで例外が出たときも yes を出す。
"""
import argparse
import json
import os
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

JST = timezone(timedelta(hours=9))
DATA = Path(__file__).resolve().parent.parent / "data"
MARK = DATA / "last_fetch.json"

# 枠をまたいでも、これより近いときは走らせない
MIN_GAP_HOURS = 6
# 「朝」の枠の始まりと終わり（日本時間の時）
MORNING_FROM, MORNING_TO = 4, 16


def slot_of(t_utc):
    """その時刻がどの枠に属するかを「2026-10-26 朝」の形で返す。"""
    t = t_utc.astimezone(JST)
    if MORNING_FROM <= t.hour < MORNING_TO:
        return f"{t:%Y-%m-%d} 朝"
    # 夜の枠は日付をまたぐ。0〜3時台は前の日の夜として数える。
    d = t.date() if t.hour >= MORNING_TO else (t - timedelta(days=1)).date()
    return f"{d:%Y-%m-%d} 夜"


def read_mark():
    try:
        o = json.loads(MARK.read_text(encoding="utf-8"))
        s = o.get("最後に取り込んだ時刻")
        if not s:
            return None, None
        t = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return t, o.get("どこから")
    except FileNotFoundError:
        return None, None
    except Exception as e:                      # 壊れていても止めない
        print(f"記録を読めませんでした（走る側に倒します）: {e}")
        return None, None


def judge(now, event):
    """(走るか, 理由) を返す。"""
    if event != "schedule":
        return True, f"手で回したぶん（{event}）なので、そのまま走ります。"
    last, src = read_mark()
    if last is None:
        return True, "取り込みの記録がまだありません。走ります。"
    gap = now - last
    hours = gap.total_seconds() / 3600
    doko = {"schedule": "定期実行", "workflow_dispatch": "手動"}.get(src, src or "不明")
    if slot_of(last) == slot_of(now):
        return False, (f"同じ枠（{slot_of(now)}）で、すでに {last.astimezone(JST):%H:%M} に"
                       f"{doko}で取り込んでいます（{hours:.1f}時間前）。"
                       "YouTubeのクォータを使わずに終わります。")
    if hours < MIN_GAP_HOURS:
        return False, (f"前の取り込み（{last.astimezone(JST):%m-%d %H:%M} / {doko}）から"
                       f"{hours:.1f}時間しかたっていません。"
                       f"{MIN_GAP_HOURS}時間あけたいので、今回は何もせず終わります。")
    return True, (f"前の取り込みは {last.astimezone(JST):%m-%d %H:%M}（{doko}）で、"
                  f"{hours:.1f}時間前。枠も変わっている（{slot_of(now)}）ので走ります。")


def mark(now, event):
    MARK.parent.mkdir(parents=True, exist_ok=True)
    MARK.write_text(json.dumps({
        "_このファイルは何か": (
            "最後に配信を取り込んだ時刻です。scripts/should_run.py が読んで、"
            "定期実行を走らせるかどうか決めます。消すと次の定期実行が必ず走ります。"
        ),
        "最後に取り込んだ時刻": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "枠": slot_of(now),
        "どこから": event,
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"取り込んだ時刻を記録しました: {now.astimezone(JST):%Y-%m-%d %H:%M} 日本時間"
          f"（{slot_of(now)} / {event}）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mark", action="store_true", help="いま取り込んだと記録する")
    ap.add_argument("--test", help="この時刻（ISO）で判断だけ試す")
    ap.add_argument("--event", help="schedule / workflow_dispatch")
    a = ap.parse_args()

    event = a.event or os.environ.get("GITHUB_EVENT_NAME") or "workflow_dispatch"
    if a.test:
        now = datetime.fromisoformat(a.test.replace("Z", "+00:00"))
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
    else:
        now = datetime.now(timezone.utc)

    if a.mark:
        mark(now, event)
        return

    go, why = judge(now, event)
    print(f"いまは {now.astimezone(JST):%Y-%m-%d %H:%M} 日本時間（{slot_of(now)}）")
    print(("走ります: " if go else "飛ばします: ") + why)
    out = os.environ.get("GITHUB_OUTPUT")
    if out and not a.test:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"go={'yes' if go else 'no'}\n")


if __name__ == "__main__":
    try:
        main()
    except Exception:                           # 壊れたら「走る」側に倒す
        traceback.print_exc()
        out = os.environ.get("GITHUB_OUTPUT")
        if out:
            with open(out, "a", encoding="utf-8") as f:
                f.write("go=yes\n")
        print("関所が失敗しました。更新は止めずに走らせます。")
        sys.exit(0)
