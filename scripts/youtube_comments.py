#!/usr/bin/env python3
"""急上昇ゲームの動画から、コメント欄の声を拾ってくる。

なぜ要るか（2026-11-08 たろちんさん）:

  > 「配信者がウケているのかゲームがウケているのかを分析して説明する」のが理想。
  > Xはユーザーの声を分析しているからそれができる。

ハヤリゲーが持っていたのは**配信者が書いた題**だけで、
**見た人の声**はどこにも無かった。コメント欄がそれにあたる。

**どの動画から取るか**（たろちんさんの指定）:

  急上昇率が高いゲーム上位10本 → その中で「1時間以下・非ライブ」→ 再生数の上位2本

  ・上位30ゲームではなく**急上昇**。毎日のコラムが書く相手はそちら。
    2026-11-08の急上昇6件のうち、**5件は30位の中に入っていなかった**
  ・「1時間以下・非ライブ」は、**生配信のアーカイブより、最初から動画の形で
    上がる切り抜き・編集動画のほうが中身のあるコメントが付きやすい**から
  ・選ぶのは build_site.py のほう（site/leads.json の comment_targets）。
    ここは取りに行くだけ

**クォータ**: commentThreads は 1回1ユニットで100件まとめて返る。
10ゲーム×2本 = **20ユニット**。1日の使用量 5,340 に対して 0.4%。

**失敗しても何も壊さない。** コメント欄を閉じている動画、鍵が無い、通信が駄目、
どれでも黙って飛ばして終わる（終了コードは必ず 0）。

走らせる順番:

    python scripts/build_site.py        ← 先。comment_targets を作る
    python scripts/youtube_comments.py  ← あと。leads.json に "comments" を足す
"""
import re
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import DATA, SITE, log, read_json, write_json, today, YouTube  # noqa: E402

KEEP = 12          # 1本あたり、残すコメントの数
CHARS = 160        # コメント1件を何字で切るか
BUDGET = 60        # この実行で使ってよいクォータの上限（念のための天井）
QUOTA_STOP = 8400  # その日すでにこれだけ使っていたら、何もしない


def fetch(yt, vid):
    """1本のコメント欄。1ユニット。取れなければ空。"""
    try:
        res = yt.call("commentThreads", 1, part="snippet", videoId=vid,
                      maxResults=100, order="relevance", textFormat="plainText")
    except (Exception, SystemExit) as e:
        # コメント欄を閉じている動画はここに来る（commentsDisabled）。普通のこと。
        # SystemExit も捕る。common.die() は SystemExit を投げるので、
        # Exception だけだと素通りして、この回の更新ごと落ちてしまう。
        log(f"    {vid} … 取れませんでした（{str(e)[:80]}）")
        return []
    out = []
    for it in res.get("items") or []:
        sn = (((it.get("snippet") or {}).get("topLevelComment") or {})
              .get("snippet") or {})
        t = re.sub(r"\s+", " ", sn.get("textDisplay") or "").strip()
        if len(t) < 4:
            continue
        out.append({"t": t[:CHARS], "likes": int(sn.get("likeCount") or 0)})
    # 「多くの人がそうだと思った」順に見たいので、高評価の多い順に並べ替える。
    # ★ここでの likes は**コメント同士を比べるため**のもので、
    #   動画の高評価数とは別物。動画の高評価数は人によって当てにならない
    #   （2026-11-08 たろちんさん）が、コメントの共感数は同じ動画の中の比較なので使える。
    out.sort(key=lambda c: -c["likes"])
    return out[:KEEP]


def main():
    leads = read_json(SITE / "leads.json", {}) or {}
    targets = leads.get("comment_targets") or []
    if not targets:
        log("leads.json に comment_targets がありません。先に build_site.py を走らせてください")
        return
    spent = (read_json(DATA / "daily" / f"{today()}.json", {}) or {}).get("quota_today") or 0
    if spent >= QUOTA_STOP:
        log(f"今日すでに {spent} 使っているので、コメントは取りません")
        return
    yt = YouTube()
    out = {}
    for g in targets:
        if yt.used + 1 > BUDGET:
            log("この実行のクォータ上限に達したのでここまでにします")
            break
        rows = []
        for v in g.get("videos") or []:
            if yt.used + 1 > BUDGET:
                break
            cs = fetch(yt, v["id"])
            if cs:
                rows.append({"id": v["id"], "t": v["t"], "c": v.get("c"),
                             "views": v.get("views"), "comments": cs})
        if rows:
            out[g["game"]] = rows
            log(f"  {g['game']} … {len(rows)}本から {sum(len(r['comments']) for r in rows)}件")
    if not out:
        log("コメントは1件も取れませんでした。leads.json はそのままにします")
        return
    leads = read_json(SITE / "leads.json", {}) or {}   # 読み直してから足す
    leads["comments"] = out
    write_json(SITE / "leads.json", leads)
    log(f"コメントを {len(out)} ゲームぶん leads.json に入れました"
        f"（使ったクォータ {yt.used}）")


if __name__ == "__main__":
    try:
        main()
    except (Exception, SystemExit) as e:         # ここで必ず止める
        # ★SystemExit も捕ること。鍵が無いと common.YouTube が die() を呼び、
        #   die() は SystemExit を投げる。Exception だけでは捕れない。
        log(f"コメントは取れませんでした（続けます）: {type(e).__name__}: {str(e)[:200]}")
