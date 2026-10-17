#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""コラムで直した所を集める。

    python3 scripts/column_fixes.py            直近30日
    python3 scripts/column_fixes.py --days 7   直近7日
    python3 scripts/column_fixes.py --all      全期間

なぜ要るか（2026-10-17 たろちんさん）
------------------------------------

    > 朝のコラムで毎日見出しや本文の修正指示を出してるんだけど、
    > 教えたことを毎回ここで報告し直さないと学習として蓄積にならないのがもどかしい。
    > 辞書修正の宿題ファイルと同様にコラムで修正した部分を覚えておいて
    > あとでまとめて反映するような仕組みにできない？

**辞書の宿題と同じ形が、そのままは作れない。** あちらが回るのは、材料が
`site/leads.json` としてリポジトリに入っているから。日曜のタスクは
毎朝の宿題ファイルを受け取れなくても、**同じ材料から作り直せる。**

コラムの直しは違う。**たろちんさんがその場で言った言葉**で、どこにも残らない。
作り直せない。だから**その日のうちにリポジトリへ運ぶ**しかない。

運び役は**コラムのJSONそのもの。** あれは毎日たろちんさんがGitHubへ上げている。
直した内容を同じファイルの中に書いておけば、**追加の手間がゼロで残る。**

    data/columns/2026-10-16.json
    {
      "game": "…", "headline": "…", "body": "…",
      "直し": [
        {"どこ": "見出し",
         "前": "ワンオペとマルチ、同じ厨房で二通りの遊ばれ方",
         "後": "ゲーム配信にもラーメンブームの兆し？",
         "なぜ": "ラーメン屋の経営シムという点が魅力。先月末も取り上げていて、
                 また盛り上がってきている点のほうが重要"}
      ]
    }

この欄は**サイトには出ない**（build_site.py の enrich_column が外す）。
Xの画像にも投稿文にも出ない。**リポジトリの中だけに残る覚え書き。**

ここはその覚え書きを集めるだけ。**EDITORIAL.md を書き換えはしない。**
文章の決まりは、たろちんさんの判断が要るところなので、
集めたものを見せて、入れるかどうかはそのとき決める。
"""
import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
JST = timezone(timedelta(hours=9))
WHERE = ("見出し", "タイトル", "本文", "見どころ", "notes", "その他")


def _today():
    return datetime.now(JST).strftime("%Y-%m-%d")


def collect(days=30):
    """[(日付, 種類, 直しの中身), …] を古い順に返す。"""
    limit = ("0000-00-00" if days is None else
             (datetime.now(JST) - timedelta(days=days)).strftime("%Y-%m-%d"))
    out = []
    for kind, sub in (("毎日", ""), ("週まとめ", "weekly"), ("月まとめ", "monthly")):
        d = DATA / "columns" / sub if sub else DATA / "columns"
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.json")):
            if f.stem < limit:
                continue
            try:
                col = json.loads(f.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                continue
            if not isinstance(col, dict):
                continue
            fixes = col.get("直し")
            if not isinstance(fixes, list):
                continue
            for x in fixes:
                if isinstance(x, dict) and (x.get("後") or x.get("なぜ")):
                    out.append((f.stem, kind, x))
    out.sort(key=lambda r: r[0])
    return out


def check(col):
    """「直し」の形がおかしくないかを返す（check_column.py から呼ぶ）。"""
    bad = []
    fixes = col.get("直し")
    if fixes is None:
        return bad
    if not isinstance(fixes, list):
        return ["「直し」はリストにしてください（[{…}, {…}]）"]
    for i, x in enumerate(fixes, 1):
        if not isinstance(x, dict):
            bad.append(f"「直し」の{i}つめがオブジェクトではありません")
            continue
        if not str(x.get("なぜ") or "").strip():
            bad.append(f"「直し」の{i}つめに「なぜ」がありません。"
                       "直した理由がいちばん大事な部分です"
                       "（前後だけ残しても、あとから決まりに直せません）")
        w = str(x.get("どこ") or "").strip()
        if w and w not in WHERE:
            bad.append(f"「直し」の{i}つめの「どこ」が {w!r} です"
                       f"（{'／'.join(WHERE)} のどれかにしてください）")
    return bad


def main():
    ap = argparse.ArgumentParser(description="コラムで直した所を集める")
    ap.add_argument("--days", type=int, default=30, help="さかのぼる日数（既定30）")
    ap.add_argument("--all", action="store_true", help="全期間")
    args = ap.parse_args()
    rows = collect(None if args.all else args.days)
    if not rows:
        span = "全期間" if args.all else f"直近{args.days}日"
        print(f"{span}に、コラムの直しの記録はありませんでした。")
        print("（コラムのJSONに「直し」の欄が書かれていれば、ここに出ます）")
        return 0

    print(f"コラムの直し {len(rows)} 件（{rows[0][0]} 〜 {rows[-1][0]}）\n")
    by_where = {}
    for day, kind, x in rows:
        w = str(x.get("どこ") or "その他").strip() or "その他"
        by_where.setdefault(w, []).append((day, kind, x))

    for w in sorted(by_where, key=lambda k: -len(by_where[k])):
        print(f"■ {w}（{len(by_where[w])}件）")
        for day, kind, x in by_where[w]:
            print(f"  {day}（{kind}）")
            if x.get("前"):
                print(f"    ✗ {x['前']}")
            if x.get("後"):
                print(f"    ○ {x['後']}")
            if x.get("なぜ"):
                print(f"    なぜ: {x['なぜ']}")
        print()

    print("―― ここから先は人が決めること ――")
    print("同じ理由が3回以上出ていたら、それは**決まりにする頃合い**です。")
    print("EDITORIAL.md のどの章に足すかを決めて、開発用のチャットで直してください。")
    print("1回しか出ていないものは、まだその日の判断かもしれません。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
