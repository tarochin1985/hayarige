#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""辞書の直しを1回で当てて、1回で確かめる。

    python3 scripts/fix_dict.py data/直し/2026-10-07.json
    python3 scripts/fix_dict.py data/直し/2026-10-07.json --full   # 全タイトルで照合
    python3 scripts/fix_dict.py data/直し/2026-10-07.json --dry    # 当てずに見るだけ

なぜ作ったか（2026-10-07 たろちんさん）
--------------------------------------
    > あと毎日辞書の穴を修正するのに大量のトークンを必要としている気がする。
    > 何か効率のいい方法はないだろうか？

毎回やっていたことは同じだった。カタログを引く → 辞書に足す →
全タイトル35,000本で前後を比べる → 消えた行が無いか origin と見比べる →
変な文字が混ざっていないか見る。**手で10回以上やりとりしていた。**
ここにまとめてある。

速いのはなぜか
--------------
前後比較は、ふだん**全タイトルを照合する必要がない。** 辞書に別名を足して
結果が変わりうるのは、

  ・その別名の字を含む配信（新しく当たるかもしれない）
  ・いま、触った行に入っている配信（取られるかもしれない）
  ・外した別名・止めた別名の字を含む配信

の3つだけ。これは証明できる絞り込みなので、`--full` と答えが変わらない。
1,000〜2,000本で済むので30秒ほどで終わる。
**辞書の作りそのものを変えた日（match.py を直した日）は `--full`。**

直しファイルの書き方
--------------------
    {
      "メモ": "2026-10-07 辞書の穴",
      "別名":   { "ゲームのキー": ["足す別名", ...] },
      "表示名": { "ゲームのキー": "画面に出す名前" },
      "機種":   { "ゲームのキー": ["pc", "console"] },
      "別名をやめる": { "ゲームのキー": ["外す別名", ...] },
      "行をやめる": ["畳む行のキー", ...],
      "別名を止める": ["カタログの別名を無効にする語", ...],
      "見落としから消す語": ["配信のラベルなど", ...]
    }

どれも書かなくてよい。キーがカタログに無ければ、そのキー自体が
新しいゲームの名前になる（aliases.json のふだんの決まりと同じ）。
"""
import argparse
import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import match as M                                      # noqa: E402
from common import DATA, read_json                     # noqa: E402

FILES = {
    "別名": "aliases.json",
    "表示名": "display_names.json",
    "機種": "platforms.json",
    "別名を止める": "alias_blocklist.json",
}
# 混ざると気づきにくい字（過去に4回やった）。キリル・ハングル・置換文字・ゼロ幅
ODD = re.compile(r"[Ѐ-ӿ가-힯�​-‏]")


def load(name):
    return json.load(open(DATA / name, encoding="utf-8"))


def save(name, obj):
    with open(DATA / name, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
        f.write("\n")


def unique_titles():
    """動画ID → (題名, チャンネル)。同じ動画が何日も出るので畳む。"""
    out = {}
    for f in sorted((DATA / "daily").glob("*.json")):
        for v in (read_json(f, {}) or {}).get("videos", []):
            out[v["id"]] = (v.get("title") or "", v.get("channel") or "")
    return out


def touched_games(patch, idx):
    names = set()
    for key in ("別名", "別名をやめる", "表示名", "機種"):
        names |= set((patch.get(key) or {}).keys())
    names |= set(patch.get("行をやめる") or [])
    # 止める別名が、いまどのゲームに入っているかも調べる
    for a in (patch.get("別名を止める") or []):
        got = idx.exact.get(M.compact(a))
        if got:
            names.add(got[0])
    return names


def touched_words(patch, idx):
    """結果が変わりうる字を集める（詰めた形）。

    **「いま触った行に入っている配信」を、判定を回さずに拾うのが肝。**
    その配信は必ず、触った行のいまの別名のどれかを題名に含んでいる。
    だから「触った行のいまの別名」も字として集めておけば、
    文字列を含むかどうかだけで絞り込める。
    ここで判定（extract）を回すと、35,000本で5分かかって意味がなくなる。
    """
    words, games = set(), touched_games(patch, idx)
    for key in ("別名", "別名をやめる"):
        for g, lst in (patch.get(key) or {}).items():
            words.add(M.compact(g))
            words |= {M.compact(a) for a in lst}
    for g in (patch.get("行をやめる") or []):
        words.add(M.compact(g))
        words |= {M.compact(a) for a in load("aliases.json").get(g, [])}
    for a in (patch.get("別名を止める") or []):
        words.add(M.compact(a))
    # 触った行の、いまの別名（手で足したぶん）
    al = load("aliases.json")
    for g in games:
        words.add(M.compact(g))
        words |= {M.compact(a) for a in al.get(g, [])}
    # 触った行の、カタログ側の別名
    for cg in M.catalogue():
        if cg["name"] in games:
            words.add(M.compact(cg["name"]))
            words |= {M.compact(a) for a in (cg.get("alias") or [])}
    return {w for w in words if len(w) >= 2}


def judge(titles, idx):
    out = {}
    for vid, (t, ch) in titles.items():
        g, how = M.extract(t, idx, fallback=True)
        out[vid] = g if how == "dict" else None
    return out


def pick(titles, patch, idx, full):
    if full:
        return titles
    words = touched_words(patch, idx)
    return {vid: v for vid, v in titles.items()
            if any(w in M.compact(v[0]) for w in words)}


def apply_patch(patch):
    """直しを当てる。**代入ではなく足し合わせる**（2026-10-05に上書き事故）。"""
    report = []
    al = load("aliases.json")
    for g, lst in (patch.get("別名") or {}).items():
        cur = al.setdefault(g, [])
        for a in lst:
            if a in cur:
                raise SystemExit(f"もう入っています: {g} の別名 {a!r}")
            cur.append(a)
        report.append(f"別名 {g} に {len(lst)}個")
    for g, lst in (patch.get("別名をやめる") or {}).items():
        if g not in al:
            raise SystemExit(f"行がありません: {g}")
        for a in lst:
            if a not in al[g]:
                raise SystemExit(f"{g} に {a!r} はありません")
            al[g].remove(a)
        report.append(f"別名 {g} から {len(lst)}個を外した")
    for g in (patch.get("行をやめる") or []):
        # 同じゲームの行が2つに割れていたときに畳む。**別名は先に移してから。**
        if g not in al:
            raise SystemExit(f"行がありません: {g}")
        if al[g]:
            raise SystemExit(f"{g} に別名が残っています。先に移してください: {al[g]}")
        del al[g]
        report.append(f"行 {g} をやめた")
    save("aliases.json", al)

    dn = load("display_names.json")
    for g, v in (patch.get("表示名") or {}).items():
        if dn.get(g) not in (None, v):
            raise SystemExit(f"表示名が既に別の値です: {g} = {dn[g]!r}。"
                             "変えるなら理由を確かめてから手で直してください"
                             "（URLが変わります）")
        dn[g] = v
    save("display_names.json", dn)

    pf = load("platforms.json")
    for g, v in (patch.get("機種") or {}).items():
        pf[g] = v
    save("platforms.json", pf)

    ab = load("alias_blocklist.json")
    for a in (patch.get("別名を止める") or []):
        if a in ab:
            raise SystemExit(f"もう止めています: {a!r}")
        ab.append(a)
    save("alias_blocklist.json", ab)

    mb = load("miss_blocklist.json")
    for w in (patch.get("見落としから消す語") or []):
        if w in mb["語"]:
            raise SystemExit(f"もう入っています: {w!r}")
        mb["語"].append(w)
    save("miss_blocklist.json", mb)
    return report


def checks(patch=None, live=None):
    """渡す前に毎回見ていたものを、まとめてここで見る。

    patch … 直しの中身。**そこで宣言した削除は警告しない**
            （宣言どおりの削除まで毎回出ると、人が読むのをやめる）
    live  … いま本数があるゲーム名の集合。表示名の重なりは、
            **両方に本数があるときだけ**知らせる
    """
    patch = patch or {}
    live = live or set()
    bad = []
    al = load("aliases.json")
    # 1) 同じ別名が2つの行に入っていないか（どちらが勝つか順番で決まってしまう）
    owner = {}
    for g, lst in al.items():
        for a in [g] + list(lst):
            c = M.compact(a)
            if len(c) < 2:
                continue
            if c in owner and owner[c] != g:
                bad.append(f"同じ別名が2行にあります: {a!r} → {owner[c]!r} と {g!r}")
            owner[c] = g
    # 2) 変な字
    for name in ["aliases.json", "display_names.json", "platforms.json",
                 "alias_blocklist.json", "miss_blocklist.json"]:
        s = (DATA / name).read_text(encoding="utf-8")
        json.loads(s)
        odd = ODD.findall(s)
        if odd:
            bad.append(f"{name} に変な字: {sorted(set(odd))}")
        if s != unicodedata.normalize("NFC", s):
            bad.append(f"{name} の文字の形が揺れています（NFC でない）")
    # 3) 表示名が同じになる行が2つ以上ないか
    #    ランキングに同じ名前が2つ並ぶ。見落としリストには出ないので、
    #    こちらで見ないと誰も気づけない（2026-10-07に日本事故物件監視協会で発覚）
    d = M.load_display()
    names = set(al) | {g["name"] for g in M.catalogue()}
    seen = {}
    for g in names:
        disp = d.get(g, g)
        if disp in seen and seen[disp] != g:
            if g in live and seen[disp] in live:
                bad.append(f"表示名が同じ行が2つあり、どちらにも本数があります: "
                           f"「{disp}」 ← {seen[disp]!r} と {g!r}")
        if g in live or disp not in seen:
            seen[disp] = g
    # 4) origin から消えた行（意図しない削除を見つける）
    for name in ["aliases.json", "display_names.json", "platforms.json",
                 "alias_blocklist.json", "miss_blocklist.json"]:
        try:
            old = subprocess.run(
                ["git", "show", f"origin/main:data/{name}"],
                cwd=DATA.parent, capture_output=True, text=True, timeout=30)
            if old.returncode:
                continue
            o, n = json.loads(old.stdout), load(name)
            if isinstance(o, dict) and isinstance(n, dict):
                told_rows = set(patch.get("行をやめる") or [])
                told = patch.get("別名をやめる") or {}
                gone = [k for k in o if k not in n and k not in told_rows]
                if gone:
                    bad.append(f"{name} から消えた行: {gone}")
                for k in o:
                    if k in n and isinstance(o[k], list) \
                            and isinstance(n[k], list):
                        lost = [x for x in o[k] if x not in n[k]
                                and x not in told.get(k, [])]
                        if lost:
                            bad.append(f"{name} の {k!r} から消えた別名: {lost}")
            elif isinstance(o, list) and isinstance(n, list):
                gone = [x for x in o if x not in n]
                if gone:
                    bad.append(f"{name} から消えた語: {gone}")
        except Exception:
            pass
    return bad


def main():
    ap = argparse.ArgumentParser(description="辞書の直しを当てて確かめる")
    ap.add_argument("patch", help="直しを書いたJSON")
    ap.add_argument("--full", action="store_true",
                    help="全タイトルで照合する（match.py を直した日）")
    ap.add_argument("--dry", action="store_true", help="当てずに見るだけ")
    a = ap.parse_args()

    patch = json.load(open(a.patch, encoding="utf-8"))
    print(f"直し: {patch.get('メモ') or a.patch}")

    titles = unique_titles()
    idx = M.build_index()
    sub = pick(titles, patch, idx, a.full)
    print(f"のべ {len(titles)} 本のうち、"
          f"{'全部' if a.full else f'影響しうる {len(sub)} 本'}を照合します")
    before = judge(sub, idx)
    if a.dry:
        print("（--dry なので当てません）")
        return 0

    for line in apply_patch(patch):
        print("  " + line)

    idx2 = M.build_index()
    d = M.load_display()
    new, lost, moved = [], [], []
    for vid, (t, ch) in sub.items():
        g, how = M.extract(t, idx2, fallback=True)
        af, bf = (g if how == "dict" else None), before.get(vid)
        if af == bf:
            continue
        if bf is None:
            new.append((af, t, ch))
        elif af is None:
            lost.append((bf, t, ch))
        else:
            moved.append((bf, af, t, ch))

    def tally(rows, i=0):
        c = {}
        for r in rows:
            c.setdefault(r[i], []).append(r)
        return sorted(c.items(), key=lambda x: -len(x[1]))

    print(f"\n新しく {len(new)}本 / 失った {len(lost)}本 / 移った {len(moved)}本")
    for g, rows in tally(new):
        print(f"  新 {d.get(g, g)}  {len(rows)}本 / "
              f"{len({r[2] for r in rows})}ch")
    for (bf, af), rows in tally([((r[0], r[1]), r) for r in moved]):
        print(f"  移 {d.get(bf, bf)} → {d.get(af, af)}  {len(rows)}本")
    if lost:
        print("  ★失った配信があります。意図したものか必ず見てください")
        for g, t, ch in lost:
            print(f"     {d.get(g, g)} ← {t[:80]}  ({ch})")

    # 直したあとに本数があるゲーム（照合した範囲ぶん）。
    # 範囲の外は触っていないので、そこだけの重なりは今回の直しのせいではない
    after_live = set()
    for vid, (t, ch) in sub.items():
        g, how = M.extract(t, idx2, fallback=True)
        if how == "dict":
            after_live.add(g)
    bad = checks(patch, after_live)
    print("\n見張り: " + ("問題なし" if not bad else f"{len(bad)}件"))
    for b in bad:
        print("  ⚠️ " + b)
    return 1 if (lost or bad) else 0


if __name__ == "__main__":
    sys.exit(main())
