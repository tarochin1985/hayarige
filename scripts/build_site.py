#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""集計してサイトを書き出す。fetch_daily.py のあとに動かす。

出力: site/index.html と site/data.json
"""
import html
import json
import urllib.parse
import hashlib
import math, re
from collections import defaultdict, Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, quote_plus
from common import DATA, SITE, JST, log, read_json, write_json, today
import match as M
from check_column import load_valid, HEDGE, BAD_SOURCE

DAYS = 7
MIN_FOR_MOMENTUM = 3          # 急上昇の対象にする最低本数（少数のブレを弾く）
MIN_HISTORY = 4               # 急上昇を出すのに必要な「実データのある日数」
RISING_MIN_CHANNELS = 3       # 急上昇に載せる最低チャンネル数（下の rising に理由）
RISING_N = 6                  # 急上昇に出す件数
UNKNOWN_ALERT = 3             # 未判定のタイトルを「辞書の穴」として知らせるチャンネル数
MISS_DAYS = 7                 # 見落とし候補を何日ぶん合わせて数えるか
MISS_ALERT = 3                # 「よく出る未知語」として知らせるチャンネル数
MISS_NEAR = 12                # カタログ前方一致の候補を何件まで出すか
MISS_WIDE = 20                # よく出る未知語を何件まで出すか
NOTES_MAX = 4                 # 「今日の見どころ」に並べる行数の上限
W = {"videos": 0.30, "channels": 0.35, "views": 0.35}

# 1人が同じゲームを1日に何本も出したときの数え方。
# site_config.json の per_channel で切り替える。
#
# 毎日決まったチャンネルが同じゲームを何本も上げているために、
# 順位が動かなくなる、という話から入れた（2026-09-19 たろちんさん）。
# 実際、パズル&ドラゴンズは3チャンネル14本で、うち1つが再生数の65%を
# 占めていた。「何人が配信したか」を見たいサイトなので、1人の連投で
# 数字が積み上がるのは趣旨と合わない。
#
# 2本目以降を何割として数えるか:
#   "全部数える"      1.0 … 以前の動き
#   "2本目から半分"    0.5 … 既定。連投は効くが、効きが半分になる
#   "1人1件"         0.0 … 1人が何本出しても1件・いちばん伸びた1本だけ
#
# 本数にも再生数にも同じ割引をかける。片方だけだと、
# 「本数は1件なのに再生数は3本ぶん」という食い違いが出る。
PER_CHANNEL = {"全部数える": 1.0, "2本目から半分": 0.5, "1人1件": 0.0}
PER_CHANNEL_DEFAULT = "2本目から半分"

# 今日のコラムがまだ無いとき、何日前まで さかのぼって表示するか。
# 0にすると、今日の分が無い日はコラム欄が消える（以前の動き）。
COLUMN_FALLBACK_DAYS = 7

# 見出しの頭に付ける印。ここだけ読めば今日の話が分かる、という目印。
# 形を変えるときはここだけ直せばよい。サイトのテンプレートには __POINT__ として
# 埋め込まれ、ツイート用カード（scripts/make_card.py）はここから読み込む。
# 別の形にしたいとき用の控え:
#   ピン  <path fill-rule="evenodd" d="M12 2a7 7 0 00-7 7c0 5.2 7 13 7 13s7-7.8 7-13a7 7 0 00-7-7zm0 9.6A2.6 2.6 0 1112 6.4a2.6 2.6 0 010 5.2z"/>
#   電球  <path d="M12 2a6.2 6.2 0 00-3.4 11.4c.5.4.8 1 .8 1.6v.3h5.2v-.3c0-.6.3-1.2.8-1.6A6.2 6.2 0 0012 2z"/><path d="M9.4 17h5.2v1.4H9.4z"/><path d="M10 19.6h4a2 2 0 01-4 0z"/>
POINT = ('<svg class="pt" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2.6l2.9 6.2 6.8.8-5 4.6 1.4 6.7L12 17.5 5.9 20.9l1.4-6.7-5-4.6 6.8-.8z"/></svg>')


# 判定の結果を変えうるファイル。どれかが変わったら、過去のページも作り直す。
MATCH_INPUTS = ("aliases.json", "display_names.json", "blocklist.json",
                "alias_blocklist.json", "game_blocklist.json", "platforms.json",
                "channels_manual.json", "igdb_meta.json", "site_config.json")


def matcher_fingerprint():
    """辞書まわりとページの型紙をまとめた短い文字列。変わったかどうかだけを見る。

    型紙（site/template.html）も入れている。中身は判定に関係ないが、
    **型紙を直しても過去のページが古いままになる**のを防ぐため。
    2026-09-24に、全ページに焼き込まれていた壊れたリンク（unknown.json）を
    型紙で直したとき、たまたま同じ日に辞書も変えていたから作り直された。
    辞書を触らない日に型紙だけ直すと、直らないままになる。

    この書き出しプログラム自身（build_site.py）も入れる。2026-09-26に、
    記録のページへ急上昇を残す直しを入れたとき、**型紙も一緒に直したから
    作り直された**だけだと気づいた。中身の組み立て方だけを変えた日は、
    同じ穴にはまる。作り直しは2分ほどかかるが、直したのに直らないほうが悪い。
    """
    h = hashlib.sha1()
    for name in MATCH_INPUTS:
        f = DATA / name
        h.update(name.encode())
        h.update(f.read_bytes() if f.is_file() else b"")
    for p in (SITE / "template.html", Path(__file__).resolve()):
        h.update(p.name.encode())
        h.update(p.read_bytes() if p.is_file() else b"")
    return h.hexdigest()[:16]


def load_all(days_back=30):
    """収集ファイルを全部読んで、動画IDで重複を除いた1本のリストにする。

    収集は毎回「直近48時間」を取り直すので、同じ動画が複数のファイルに入る。
    再生数はいちばん大きい（＝いちばん新しく取った）ものを採用する。

    戻り値は (動画リスト, 収集した日のリスト)。

    channels_manual.json で「外す」と書いたチャンネルは、ここでも落とす。
    集める側（fetch_daily.py）でも同じ指定を見ているが、すでに保存済みの
    ぶんはそのまま残っている。読むときにももう一度ふるいにかけておくと、
    外した効果がその日のうちに効き、過去の記録ページを作り直したときも
    同じ基準になる。
    """
    manual = read_json(DATA / "channels_manual.json", {}) or {}
    drop = {k for k, v in manual.items()
            if v == "外す" and not k.startswith("_")}
    best, runs, cut = {}, [], 0
    for f in sorted((DATA / "daily").glob("*.json")):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", f.stem):
            continue                      # .gitkeep.json などの置き石は読まない
        rec = read_json(f, None)
        if rec is None:
            continue
        runs.append(f.stem)
        for v in rec.get("videos", []):
            if v.get("channel_id") in drop:
                cut += 1
                continue
            cur = best.get(v["id"])
            if cur is None or v.get("views", 0) >= cur.get("views", 0):
                best[v["id"]] = v
    if cut:
        log(f"手で外したチャンネルの動画を {cut} 本除きました"
            f"（data/channels_manual.json に {len(drop)} チャンネル）")
    return list(best.values()), sorted(runs)


def pub_utc(v):
    """"2026-08-27T01:00:00Z" を datetime に。壊れていたら None。"""
    s = (v.get("published") or "").replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def windows(videos, runs, n=DAYS):
    """直近24時間ずつに区切って (ラベル, 動画リスト, データがあるか) を古い順に返す。

    以前は「収集ファイル1個＝1日」として数えていたが、これは間違いだった。
    実行が朝7時なら朝までの分しか入らず、夜中に回せば丸1日分入る。
    同じ『1日』のはずが実行時刻で3倍も変わってしまう。
    時計で24時間ずつ切れば、いつ実行しても同じ意味の数字になる。
    """
    now = datetime.now(timezone.utc)
    stamped = [(p, v) for v in videos if (p := pub_utc(v))]
    # どこまで遡ってデータがあると言えるか。最初に収集した日の前日まで。
    # （収集は48時間ぶんを取るが、控えめに24時間ぶんだけ数える）
    covered_from = None
    if runs:
        first = datetime.strptime(runs[0], "%Y-%m-%d").replace(tzinfo=JST)
        covered_from = first - timedelta(hours=24)

    out = []
    for k in range(n - 1, -1, -1):
        hi = now - timedelta(hours=24 * k)
        lo = hi - timedelta(hours=24)
        sel = [v for p, v in stamped if lo <= p < hi]
        ok = covered_from is not None and lo >= covered_from
        label = hi.astimezone(JST).strftime("%m/%d")
        out.append((label, sel, ok))
    return out


def by_calendar_day(videos):
    """日本時間の日付ごとに仕分ける。アーカイブ（その日の記録）に使う。"""
    out = defaultdict(list)
    for v in videos:
        p = pub_utc(v)
        if p:
            out[p.astimezone(JST).strftime("%Y-%m-%d")].append(v)
    return out


# ------------------------------------------------------------------ コラムの種
HASHTAG = re.compile(r"[#＃]([^\s#＃【】『』「」\[\]（）()]{2,40})")
# 汎用タグだけを外す。部分一致にすると #ぶいすぽマイクラ夏祭り2026 まで
# 落ちてしまうので、完全一致でのみ判定する。
TAG_NG = {M.compact(t) for t in
          ("shorts", "short", "live", "配信", "生配信", "雑談", "歌枠", "karaoke",
           "vtuber", "新人vtuber", "初見歓迎", "参加型", "個人勢",
           "ホロライブ", "にじさんじ", "ぶいすぽ", "ぶいすぽっ", "ななしいんく")}


def find_leads(videos, rows, hist, day_names):
    """「今日は何か起きたか」を、自分たちが集めたデータだけから拾う。

    まとめサイトを見に行く前の段階。ここに出たものを人が一次ソースで
    確かめてからコラムにする。ここ自体は記事ではないので公開しない。
    """
    # 1. 同じハッシュタグを、別々の配信者が使っている＝企画・大会の気配
    tags = defaultdict(set)
    for v in videos:
        for m in HASHTAG.finditer(v["title"]):
            t = M.compact(m.group(1))
            if len(t) >= 4 and t not in TAG_NG:
                tags[m.group(1)].add(v["channel"])
    events = [{"tag": "#" + k, "channels": sorted(c)}
              for k, c in tags.items() if len(c) >= 3]
    events.sort(key=lambda e: -len(e["channels"]))

    # 2. 直近の他の日には出ていなかったのに、今日は複数人が触っている
    past = [d for d in day_names[:-1] if d in hist]
    newcomers = []
    for r in rows[:25]:
        if r["channels"] < 2:
            continue
        if past and all(hist[d].get(r["canonical"], 0) == 0 for d in past):
            newcomers.append({"game": r["game"], "channels": r["channels"],
                              "videos": r["videos"]})

    # 3. 単純に、多くの配信者が同じ日に触ったもの
    wide = [{"game": r["game"], "channels": r["channels"], "videos": r["videos"]}
            for r in rows[:10] if r["channels"] >= 4]

    return {"events": events[:8], "newcomers": newcomers[:8], "wide": wide[:8]}


def find_drift(videos, idx, limit=12):
    """続編が、前作と同じ行に数えられていないか探す。

    2026-09-18に、発売初日の『空の軌跡 the 2nd』の配信20本が、前作
    『空の軌跡 the 1st』として数えられていた。辞書に『the 2nd』が
    無かったので、名前の前半だけが一致して前作に吸い込まれていた。

    これは未知タイトル一覧（/admin/）には出ない種類の事故である。判定
    そのものは成功していて、行き先だけが違うからだ。だから別に見張る。

    見張り方: 冒頭の【】に書かれた名前が「登録してある名前＋数字」の形に
    なっていて、しかもその書き方がそのゲームの配信者の3分の1以上を
    占めているとき、辞書に足りない続編があると見る。
    数字を条件にしているのは、続編・章・版の区別がほぼ必ず数字で
    書かれるから。『【モンスト参加型】』のような書き足しは数字が無いので
    出てこない。割合で足切りするのは、『【マイクラ1.21】』のような
    バージョン表記が1〜2人ぶん混ざっても騒がないようにするため。
    """
    ORD = re.compile(r"[0-9]|1st|2nd|3rd|4th|ii|iii|iv")
    # ゲーム名 → 登録してある表記（詰めた形）
    known = defaultdict(set)
    for c, (g, _) in idx.exact.items():
        known[g].add(c)
    for lst in idx.bucket.values():
        for c, _sp, g, _p in lst:
            known[g].add(c)

    ways = defaultdict(lambda: defaultdict(set))   # game -> 書かれ方 -> 配信者
    total = defaultdict(set)                       # game -> 配信者ぜんぶ
    for v in videos:
        g, how = M.extract(v["title"], idx, fallback=True)
        if how != "dict":
            continue
        total[g].add(v["channel"])
        raw = M.leading_bracket(v["title"], idx.ng)
        if not raw:
            continue
        c = M.compact(raw)
        if len(c) < 3 or c in known.get(g, ()):
            continue
        for k in known.get(g, ()):
            if len(k) < 3 or k not in c:
                continue
            rest = c.replace(k, "", 1)
            if rest and ORD.search(rest):
                ways[g][raw].add(v["channel"])
            break

    out = []
    for g, w in ways.items():
        n_all = len(total[g]) or 1
        for raw, chans in w.items():
            if len(chans) >= 3 and len(chans) * 3 >= n_all:
                out.append({"game": g, "written": raw, "channels": len(chans),
                            "of": n_all, "example": sorted(chans)[:3]})
    out.sort(key=lambda d: -d["channels"])
    return out[:limit]


# ------------------------------------------------------------ 見落とし候補
# なぜ要るか（2026-09-25）
#
#   たろちんさんから「Pogostuck は集計できているか」と聞かれて調べたところ、
#   5チャンネルが配信していたのに1本も数えられていなかった。しかも
#   **毎朝のアラートにも出ていなかった。** 理由は2つある。
#
#   (1) 「確認待ち」に入るのは、タイトルの**先頭**に【】があるものだけ。
#       match.leading_bracket() が先頭しか見ないのは、末尾の【】が
#       配信者名・事務所名であることが多いからで、これは正しい判断。
#       だが結果として、
#         「…ついに壊れる【Pogostuck/標準】」  → 末尾なので見ない
#         「ポゴ2で一発アウト」               → 括弧が無いので見ない
#       が、どこにも記録されないまま消えていた。
#   (2) 先頭に【】があった2本は拾われたが、片方は「Pogostuck」、
#       片方は「ポゴ」。**別の語として1chずつに分かれ、**
#       3ch以上という知らせる条件に届かなかった。
#
#   つまり「確認待ち」だけでは、見落としは人が気付くまで残る。
#   実際に『デスゲームの報告書』は19日間、Pogostuck は数か月それだった。
#
# そこで、括弧の位置を問わず、タイトルの中の「名前らしき部分」を全部見る
# 見張りを別に置く。判定を変えるわけではないので、順位には一切影響しない。
# 出るのは管理ページと leads.json だけで、辞書に足すかどうかは人が決める。
#
#   A案（near）カタログのゲーム名の頭と一致する語。
#       「Pogostuck」→『Pogostuck: Rage With Your Friends』のように、
#       **正式名を提案できる**ので確度が高い。1チャンネルでも出す。
#   B案（wide）カタログに無い語で、3チャンネル以上が使っているもの。
#       『デスゲームの報告書』『Feign』のように「英語名はカタログにあるが
#       日本語名が無い」型と、そもそもカタログに無い新作がここに出る。
#
# ノイズ（配信のラベル・事務所名・配信者名）は、
#   blocklist.json / match.CHANNEL_HINTS / 監視チャンネル名 で落とす。
# 落としきれない語が出たら blocklist.json に足す。足すほど静かになる。

MISS_BR = re.compile(r"[【〖『「《\[]([^】〗』」》\]]{2,40})[】〗』」》\]]")
MISS_TAG = re.compile(r"[#＃]([^\s#＃【】、。,／/]{2,30})")
MISS_SPLIT = re.compile(r"[/／|｜]")


def miss_tokens(title):
    """タイトルから「ゲーム名かもしれない部分」を取り出す。括弧の位置は問わない。

    【Pogostuck/標準】のような「ゲーム名＋自分用の印」は / で割る。
    割らないと『pogostuck標準』という一致しない語になってしまう。
    """
    out = []
    for m in MISS_BR.finditer(title):
        for part in MISS_SPLIT.split(m.group(1)):
            part = part.strip()
            if part:
                out.append(part)
    out += [m.group(1).strip() for m in MISS_TAG.finditer(title)]
    return out


def _miss_blocklist():
    """見落とし候補の一覧からだけ消す語。判定には使わないので足しても安全。

    blocklist.json のほうは判定にも使われる。そちらに短い英単語を足すと
    looks_like_noise() がその語を全部取り除いてしまうため、たとえば "live" を
    足すと『Live A Live』が『a』になって丸ごと捨てられる。だから
    「一覧に出したくないだけ」の語は、判定に触らないこちらに分けてある。
    """
    words = (read_json(DATA / "miss_blocklist.json", {}) or {}).get("語", [])
    exact, part = set(), set()
    for w in words:
        c = M.compact(w)
        if len(c) >= 6:
            part.add(c)
        elif c:
            exact.add(c)
    return exact, part


def _miss_noise():
    """配信者名と事務所名（詰めた形）。ゲーム名でないものを落とすのに使う。"""
    orgs, names = set(), set()
    for c in read_json(DATA / "channels_enriched.json", []) or []:
        a = M.compact(c.get("affiliation") or "")
        if len(a) >= 3:
            orgs.add(a)
        for k in ("name", "title"):
            n = M.compact(c.get(k) or "")
            if len(n) >= 3:
                names.add(n)
    return orgs, names


def find_misses(videos, idx, tagged=None):
    """辞書に無いまま数えられていない語を探す。順位には影響しない見張り。"""
    tagged = tagged or {}
    orgs, names = _miss_noise()
    ng_exact, ng_part = _miss_blocklist()
    # 辞書に登録済みの表記（詰めた形）。ここに在る語は「辞書の穴」ではない
    known = set(idx.exact)
    for lst in idx.bucket.values():
        for c, _sp, g, _p in lst:
            known.add(c)
    # カタログの正式名。前方一致で正式名を提案するのに使う
    cat = {}
    for g in M.catalogue():
        cat.setdefault(M.compact(g["name"]), g["name"])

    seen = defaultdict(lambda: {"word": "", "chs": set(), "n": 0, "ex": []})
    for v in videos:
        _g, how = M.extract(v["title"], idx, fallback=True)
        if how == "dict" or v["id"] in tagged:
            continue
        for tk in miss_tokens(v["title"]):
            c = M.compact(tk)
            if len(c) < 3 or c.isdigit() or M.looks_like_noise(c, idx.ng):
                continue
            if c in known or c in names or c in cat or c in ng_exact:
                continue
            if any(o in c for o in orgs) or any(h in c for h in M.CHANNEL_HINTS):
                continue
            if any(w in c for w in ng_part):
                continue
            e = seen[c]
            e["word"] = e["word"] or tk
            e["chs"].add(v.get("channel") or "")
            e["n"] += 1
            if len(e["ex"]) < 3:
                e["ex"].append({"t": v["title"], "c": v.get("channel") or "",
                                "u": f"https://www.youtube.com/watch?v={v['id']}"})

    near, wide = [], []
    for c, e in seen.items():
        sug = []
        if len(c) >= 6:
            for key, name in cat.items():
                if not key.startswith(c) or key == c:
                    continue
                # 単語の切れ目で終わっているものだけ。『pogostuck』は
                # 『pogostuck:rage…』の "rage" の直前で切れるので通る。
                km, ks = M.compact_map(name)
                if len(ks) > len(c) and ks[len(c)]:
                    sug.append(name)
        row = {"word": e["word"], "channels": len(e["chs"]), "n": e["n"],
               "examples": e["ex"]}
        if sug and len(sug) <= 3:
            near.append(dict(row, kind="near", suggest=sorted(sug)[:2]))
        elif len(e["chs"]) >= MISS_ALERT:
            wide.append(dict(row, kind="wide", suggest=[]))
    near.sort(key=lambda r: (-r["channels"], -r["n"]))
    wide.sort(key=lambda r: (-r["channels"], -r["n"]))
    return near[:MISS_NEAR] + wide[:MISS_WIDE]


def series_sig(channel_id: str, title: str) -> str:
    """連番シリーズをまとめるための署名。1人の連投で順位が動かないようにする。

    署名に配信者を含める。以前はタイトルだけで作っていたので、
    別々の配信者が同じ言い回しを使っただけで1件にまとめられていた
    （「【Minecraft】久しぶりの…」を2人が同じ日に出した、など）。
    2人が配信したなら2件である。

    まとめる範囲は集計の窓（直近24時間）と同じ。数日おきに続く長期シリーズは
    そもそも別の日に入るので、まとまらずに毎回数えられる。
    ここで1件になるのは「同じ人が同じ日に、続きものを何本も出した」場合だけ。
    """
    return (channel_id or "") + "|" + M.compact(re.sub(r"[0-9#＃]+", "", title))[:16]


TAG_MIN_CHANNELS = 3     # そのタグを使っている配信者が何人いれば企画とみなすか
TAG_MIN_EVIDENCE = 3     # うち、ゲーム名を書いてくれた動画が何本必要か
TAG_AGREE = 0.8          # そのうち何割が同じゲームを指していれば採用するか


def tag_games(videos, idx):
    """企画タグから、ゲーム名を書いていない配信のゲームを割り出す。

    大会や企画の配信は、題名がタグだけになりやすい。
    2026-09-19の #にじ遊戯王祭2026 は、13人が21本出していたのに、
    ゲーム名（遊戯王マスターデュエル）を書いていたのは6本だけだった。
    残りの15本はランキングに入らず、企画そのものが小さく見えていた。

    辞書に足して解ける問題ではない。企画名は毎回変わるし、事前には分からない。
    だから、その日のデータの中から答えを拾う。同じタグの配信のうち、
    ゲーム名を書いてくれた人が何を書いたかを見る。全員が同じゲームを
    書いているなら、書かなかった人も同じゲームである。

    安全のために3つ条件を置く。
      ・そのタグを3人以上が使っている（個人の口ぐせを拾わない）
      ・ゲーム名が判定できた動画が3本以上、しかも2人以上から出ている
      ・そのうち8割以上が同じゲームを指している
    判定に成功している動画は、絶対に書き換えない。足すのは「不明」だけ。
    """
    tags = defaultdict(lambda: {"ch": set(), "hit": Counter(),
                                "hit_ch": defaultdict(set), "miss": []})
    for v in videos:
        found = set()
        for m in HASHTAG.finditer(v["title"]):
            t = M.compact(m.group(1))
            if len(t) >= 4 and t not in TAG_NG:
                found.add(t)
        if not found:
            continue
        g, how = M.extract(v["title"], idx, fallback=True)
        for t in found:
            e = tags[t]
            e["ch"].add(v.get("channel_id"))
            if how == "dict":
                e["hit"][g] += 1
                e["hit_ch"][g].add(v.get("channel_id"))
            else:
                e["miss"].append(v["id"])

    out, notes = {}, []
    for t, e in tags.items():
        if len(e["ch"]) < TAG_MIN_CHANNELS or not e["miss"] or not e["hit"]:
            continue
        game, n = e["hit"].most_common(1)[0]
        if n < TAG_MIN_EVIDENCE or len(e["hit_ch"][game]) < 2:
            continue
        if n / sum(e["hit"].values()) < TAG_AGREE:
            continue
        for vid in e["miss"]:
            out.setdefault(vid, game)
        notes.append({"tag": t, "game": game, "evidence": n,
                      "added": len(e["miss"]), "channels": len(e["ch"])})
    notes.sort(key=lambda x: -x["added"])
    return out, notes


def per_channel(cfg):
    """site_config.json の per_channel を倍率にする。未設定なら既定値。"""
    name = str((cfg or {}).get("per_channel") or PER_CHANNEL_DEFAULT)
    if name not in PER_CHANNEL:
        log(f"per_channel の値「{name}」は使えません。"
            f"{' / '.join(PER_CHANNEL)} のどれかにしてください。"
            f"今回は「{PER_CHANNEL_DEFAULT}」で動かします。")
        name = PER_CHANNEL_DEFAULT
    return PER_CHANNEL[name]


def discount(e, d):
    """1人の連投を割り引いた「件数」と「再生数」を出す。

    まず同じ人の同じ続きもの（series_sig）を1本にまとめ、そのうえで
    2本目以降を d 倍として数える。本数にも再生数にも同じ倍率をかける。
    再生数は、その人のいちばん伸びた1本を丸ごと、残りを d 倍で足す。
    d=1.0 なら以前と同じ、d=0.0 なら「1人につき1件・1本だけ」。
    """
    n = 0.0
    w = 0
    for sigs in e["by_ch"].values():
        vs = sorted(sigs.values(), reverse=True)
        n += 1 + d * (len(vs) - 1)
        w += vs[0] + round(d * sum(vs[1:]))
    return n, w


def tally(videos, idx, d=None):
    d = PER_CHANNEL[PER_CHANNEL_DEFAULT] if d is None else d
    games = defaultdict(lambda: {"raw": 0, "channels": set(),
                                 "by_ch": defaultdict(dict),
                                 "streams": [], "titles": [],
                                 "orgs": defaultdict(int)})
    unknown = []
    by_tag, _ = tag_games(videos, idx)
    for v in videos:
        g, how = M.extract(v["title"], idx, fallback=True)
        if how != "dict" and v["id"] in by_tag:
            g, how = by_tag[v["id"]], "dict"
        if how == "dict":
            e = games[g]
            e["raw"] += 1
            e["channels"].add(v["channel_id"])
            sig = series_sig(v.get("channel_id"), v["title"])
            cur = e["by_ch"][v["channel_id"]]
            cur[sig] = max(cur.get(sig, 0), v.get("views", 0))
            e["titles"].append(v["title"])
            e["orgs"][v.get("affiliation") or "個人・その他"] += 1
            if len(e["streams"]) < 12:
                e["streams"].append({"t": v["title"], "c": v["channel"],
                                     "u": f"https://www.youtube.com/watch?v={v['id']}",
                                     "th": v.get("thumb", ""), "v": v.get("views", 0)})
        elif how == "unknown":
            unknown.append({"title": v["title"], "guess": g, "channel": v["channel"],
                            "u": f"https://www.youtube.com/watch?v={v['id']}"})
    for e in games.values():
        e["n"], e["views"] = discount(e, d)
    return games, unknown


def choose_name(canonical, jp, titles, override):
    """英語名と日本語名のどちらで表示するかを、実際の配信タイトルから決める。
    配信者が『APEX』と書くならAPEX、『日本事故物件監視協会』と書くならそちら。"""
    if canonical in override:
        return override[canonical]
    if not jp or jp == canonical:
        return canonical
    blob = " ".join(M.compact(t) for t in titles)
    return jp if blob.count(M.compact(jp)) >= blob.count(M.compact(canonical)) else canonical


# ------------------------------------------------------------ 静的HTML
# ページの中身は、これまで全部JavaScriptで組み立てていた。
# そのため <script> を除いたHTMLには380文字しか無く、ゲーム名もコラム本文も
# 1文字も入っていなかった。検索エンジンはJavaScriptを動かして読むが後回しに
# されるし、それ以外の読み手にはそもそも届かない。
# このサイトが拾えるはずの検索は「ゲーム名 + 配信」なのに、そのゲーム名が
# HTMLに無いのは致命的なので、同じ中身をHTMLとしても書き出しておく。
# JavaScriptが動く環境では、読み込み後に同じ内容で描き直される。

def e(s):
    return html.escape(str(s if s is not None else ""))


def man(n):
    n = int(n or 0)
    if n >= 100000:
        return f"{n // 10000}万"
    if n >= 10000:
        return f"{n / 10000:.1f}万"
    return f"{n:,}"


def nav_html(data, home):
    """ページ上部のリンク。JavaScriptなしでも出るように、HTMLにも書いておく。
    「このサイトについて」はフッターだけだと見つけてもらえない。"""
    a = []
    if data.get("mode") == "page":
        a.append((home, "今日のランキングへ"))
        a.append((home + "matome/", "週・月のまとめ"))
        a.append((home + "archive/", "これまでの記録"))
        a.append((home + "search/", "ゲームを探す"))
    elif data.get("mode") == "archive":
        a.append((home, "今日のランキング"))
        a.append((home + "matome/", "週・月のまとめ"))
        a.append((home + "search/", "ゲームを探す"))
        a.append((home + "about/", "このサイトについて"))
    elif data.get("mode") == "admin":
        return ""
    else:
        if data.get("view") == "archive":
            a.append((home, "今日のランキングへ"))
        a.append((home + "matome/", "週・月のまとめ"))
        a.append((home + "archive/", "これまでの記録"))
        a.append((home + "search/", "ゲームを探す"))
        a.append((home + "about/", "このサイトについて"))
    return "".join(f'<a href="{e(u)}">{e(t)}</a>' for u, t in a)


def enrich_column(column, rows):
    """コラムに画像とSteamリンクを持たせる。

    表示側でランキングから同名を探す作りにしていた時期は、取り上げたゲームが
    31位以下に落ちた瞬間に画像が消えていた（8/29のみんなのGOLF）。
    順位に関係なく出したいので、30位で切る前の全ゲームから引く。

    過去の日のページを作り直すときにも同じ処理が要る。ここを今日のぶんだけに
    していたため、記録に残ったコラムのサムネイルが全部消えていた（2026-09-15）。
    """
    if not column:
        return column
    cr = next((r for r in rows if r["game"] == column.get("game")), None)
    if cr:
        st = cr.get("streams") or []
        if st and st[0].get("th"):
            column["hero"] = st[0]["th"]
            # 画像を借りた相手。出どころを書かずに使わないため、
            # サムネイルと一緒に必ず持ち回る。
            column["hero_by"] = st[0].get("c", "")
        # Xに貼る画像用。小さいものを3枚並べる。1枚を大きく使うより、
        # 借りている度合いが下がる。出どころは1枚ずつ添える。
        column["pics"] = [{"th": s.get("th", ""), "by": s.get("c", "")}
                          for s in st[:3] if s.get("th")]
        if cr.get("steam"):
            column["steam"] = cr["steam"]
    if not column.get("hero"):
        # ランキングに1本も無いゲーム（配信が終わって24時間を過ぎた等）でも、
        # 出典のYouTube動画からサムネイルを作れる。コラムの game の書き方が
        # ランキングの表記とずれている日も、ここで拾える。
        for src in column.get("sources") or []:
            m = re.search(r"(?:youtube\.com/watch\?v=|youtu\.be/)([\w-]{11})",
                          str(src.get("u", "")))
            if m:
                column["hero"] = f"https://i.ytimg.com/vi/{m.group(1)}/mqdefault.jpg"
                column["hero_by"] = column.get("hero_by", "")
                break
    return column


def _pick_stale(col, data):
    """そのコラムが、そのページの日付より前に書かれたものか。"""
    if not col:
        return False
    return col.get("date", data.get("date")) != data.get("date")


def pick_title(col, data):
    if data.get("view") == "archive":
        return "この日の注目ゲーム"
    if _pick_stale(col, data):
        d = col["date"]
        return f"{int(d[5:7])}月{int(d[8:10])}日の注目ゲーム"
    return "今日の注目ゲーム"


def pick_note(col, data):
    if data.get("view") == "archive" or _pick_stale(col, data):
        return "この日、数字が動いた理由"
    return "なぜ今このゲームが伸びているのか"


def ssr_pick(col):
    """コラム。サイトでいちばん読まれる部分なので、必ずHTMLに出す。"""
    if not col:
        return ""
    parts = []
    if col.get("hero"):
        parts.append(f'<img class="heroimg" src="{e(col["hero"])}" alt="" loading="lazy">')
    body = ['<div class="ptxt">', '<span class="badge">PICK UP</span>',
            f'<div class="g">{e(col.get("game"))}</div>',
            f'<div class="hl">{POINT}{e(col.get("headline"))}</div>',
            f'<p>{e(col.get("body"))}</p>']
    people = col.get("people") or []
    if people:
        body.append('<div class="who">'
                    + "".join(f"<span>{e(x)}</span>" for x in people) + "</div>")
    srcs = col.get("sources") or []
    if srcs:
        body.append('<div class="src">' + "".join(
            f'<a href="{e(s.get("u"))}" target="_blank" rel="noopener">{e(s.get("t"))}</a>'
            for s in srcs) + "</div>")
    body.append("</div>")
    return ("".join(parts) + "".join(body))


def ssr_notes(col):
    """今日の見どころ。JavaScriptが動かなくても読めるようにする。

    カードに出ているのは、サムネイル・ゲーム名・倍率・件数だけ。
    **そこから読み取れないこと**を短い文で足す場所（2026-09-26 たろちんさん）。
      「GAMEゆうなchの新作『ダービースタリオン2』配信に注目」
      「2年以上前のゲームである『風来のシレン6』が上昇」
    書くのは人（朝の定期実行）で、ここは受け取って並べるだけ。
    """
    ns = [str(x).strip() for x in ((col or {}).get("notes") or []) if str(x).strip()]
    return "".join(f"<li>{e(n)}</li>" for n in ns[:NOTES_MAX])


def ssr_hot(rising, archive=False):
    """急上昇のカード。JavaScriptが動かなくても読めるようにする。

    ここはこのサイトの主役なので、検索エンジンにも中身が渡るようにしておく。
    JSが動けば同じ内容で描き直される。
    """
    out = []
    day = "この日" if archive else "今日"
    for r in rising or []:
        st = (r.get("streams") or [{}])[0]
        th = st.get("th") or ""
        # JS側の toFixed(1) と同じ丸め方にする（6.25 は 6.3）。Pythonの書式指定は
        # 6.2 にするので、そのままだと読み込んだ直後に数字がチラッと変わる。
        mul = math.floor((r.get("growth") or 1) * 10 + 0.5) / 10
        img = (f'<img src="{e(th)}" alt="" loading="lazy">' if th
               else '<span class="ph"></span>')
        out.append(
            '<article class="hotcard"><span class="hbtn"><span class="hth">'
            f'{img}<span class="mul">×{mul:.1f}</span></span>'
            f'<span class="hbody"><span class="n">{e(r["game"])}</span>'
            f'<span class="delta"><span>ふだん {r.get("base")}件</span>'
            f'<b>{day} {r["videos"]}件</b></span>'
            f'<span class="f"><span>{r["channels"]}チャンネルが配信</span>'
            f'<span>{man(r["views"])}回 視聴</span></span></span></span></article>')
    return "".join(out)


def ssr_arch(archive, home):
    """これまでの記録の一覧。JavaScriptが動かなくても読めるようにする。

    ここに並べるのは、その日の上位ゲームではなく**その日の急上昇**。
    32日ぶんで数えたところ、上位5に出たゲームは24種類しかなく、
    Apexは32日中32日、ストリートファイター6は31日、マイクラは27日出ていた。
    前日と同じ顔ぶれが平均3.7/5。**一覧に並べても、ほぼ同じ行が続くだけ**だった。
    同じ日数で急上昇3に出たゲームは63種類、前日と同じ顔ぶれは平均0.4/3。
    「次に流行るゲーム」を見にくるサイトの記録としては、こちらが中身になる
    （2026-09-26 たろちんさん）。
    """
    out = []
    for en in archive or []:
        col = en.get("column") or {}
        gs = "".join(
            f'<span class="g">{e(g["game"])}'
            f'<span class="mu">×{math.floor((g.get("growth") or 1) * 10 + 0.5) / 10:.1f}</span>'
            '</span>' for g in (en.get("hot") or []))
        if not gs:      # 倍率を出せない日（データが足りない古い日）は、これまでどおり上位を出す
            gs = "".join(f'<span class="g">{e(g["game"])}</span>'
                         for g in (en.get("top") or [])[:3])
        out.append(
            f'<a class="day" href="{home}d/{e(en["date"])}/">'
            f'<span class="dt">{e(en["date"].replace("-", "."))}</span><span class="bd">'
            + (f'<span class="hl">{e(col.get("game", ""))}｜{e(col.get("headline", ""))}</span>'
               if col else "")
            + f'<span class="gs">{gs}</span>'
            f'<span class="st">配信 {en["videos"]}本 / {en["channels"]}ch / {en["games"]}ゲーム</span>'
            '</span></a>')
    return "".join(out)


def ssr_cards(rows):
    """上位3件のカード。"""
    out = []
    for r in rows[:3]:
        st = (r.get("streams") or [{}])[0]
        th = st.get("th") or ""
        out.append(
            f'<div class="gcard"><span class="th">'
            + (f'<img src="{e(th)}" alt="" loading="lazy">' if th else "")
            + f'<span class="rank">{r["rank"]}</span></span>'
            f'<span class="gm"><b>{e(r["game"])}</b>'
            f'<span class="nums"><i>{r["videos"]}</i>件 <i>{r["channels"]}</i>ch '
            f'<i>{man(r["views"])}</i>回</span>'
            + (f'<span class="tp">{e(st.get("c"))}「{e(st.get("t"))}」</span>' if st.get("t") else "")
            + "</span></div>")
    return "".join(out)


def ssr_rows(rows):
    """4位以下の一覧。ゲーム名と件数を、文字としてHTMLに残すのが目的。"""
    out = []
    for r in rows[3:]:
        st = (r.get("streams") or [{}])[0]
        th = st.get("th") or ""
        out.append(
            f'<div class="lrow"><span class="rk2">{r["rank"]}</span>'
            + (f'<img src="{e(th)}" alt="" loading="lazy">' if th else "")
            + f'<span class="nm2"><b>{e(r["game"])}</b>'
              f'<span>{r["videos"]}件 ・ {r["channels"]}ch ・ {man(r["views"])}回</span></span>'
              "</div>")
    return "".join(out)


KEEP_DAYS = 30      # YouTubeのAPI規約で、配信タイトルなどを保存できる上限


def purge_old(site_url):
    """30日を過ぎた記録から、YouTubeから取った文字（配信タイトル・チャンネル名・
    サムネイル）を消す。ゲーム名と件数──こちらが数えた結果──だけを残す。

    YouTubeの開発者ポリシーにこう定められている。
      「API Clients may store all other types of Authorized Data ...
        for no longer than 30 calendar days. After 30 calendar days,
        the API Client must either delete or refresh the stored data.」
    再生数などの数値は別枠だが、配信タイトルとチャンネル名はこれに当たる。

    独自に計算したスコアや集計値の公開は、ポリシーが明示的に認めている。
    なので「その日どのゲームが何件配信されたか」は残せる。消すのは、
    YouTubeから借りてきた文字と画像のほうだけ。

    元の日別ファイル（data/daily/）も同時に消す。あちらが本体なので、
    ページだけ消しても意味がない。
    """
    limit = (datetime.now(JST) - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%d")
    gone = 0
    for f in sorted((DATA / "daily").glob("*.json")):
        day = f.stem
        if len(day) == 10 and day < limit:
            f.unlink()
            gone += 1
    if gone:
        log(f"30日を過ぎた収集ファイルを {gone} 日分削除しました（〜{limit}）")

    fixed = 0
    for d in sorted((SITE / "d").glob("*")):
        if not d.is_dir() or d.name >= limit:
            continue
        page = d / "index.html"
        if not page.exists():
            continue
        h = page.read_text(encoding="utf-8")
        key = "const DATA = "
        if key not in h:
            continue
        try:
            obj, _ = json.JSONDecoder().raw_decode(h[h.index(key) + len(key):])
        except ValueError:
            continue
        if obj.get("purged"):
            continue
        # ranking だけでなく rising・spread にも同じ配信一覧が入っている。
        # 1か所ずつ書くと取りこぼすので、まるごと歩いて外す。
        def strip(node):
            if isinstance(node, dict):
                node.pop("streams", None)
                for v in node.values():
                    strip(v)
            elif isinstance(node, list):
                for v in node:
                    strip(v)
        for k in ("ranking", "rising", "spread", "momentum"):
            strip(obj.get(k))
        # コラムは扱いを分ける。本文も出典もこちらが書いた記事の一部で、
        # 出典を消すと「裏が取れることが読者に確認できる」という
        # このサイトの土台が崩れる。引用と出典の明示は残す。
        # 見出し画像だけはYouTubeのサムネイルそのものなので外す。
        if isinstance(obj.get("column"), dict):
            obj["column"].pop("hero", None)
        obj["purged"] = True
        render_page(page.relative_to(SITE).as_posix(), obj, 2, site_url)
        fixed += 1
    if fixed:
        log(f"30日を過ぎた記録 {fixed} 日分から、配信タイトルを外しました")


def analytics_html():
    """アクセス解析のタグ。data/site_config.json に token を入れると出る。

    Cloudflare Web Analytics を使う。Cookieを置かず個人を追いかけないので、
    同意バナーが要らない。いまは「何人来たか」が分かれば十分。
    """
    cfg = read_json(DATA / "site_config.json", {}) or {}
    tok = (cfg.get("analytics_token") or "").strip()
    if not tok:
        return ""
    return ('<script defer src="https://static.cloudflareinsights.com/beacon.min.js" '
            f"data-cf-beacon='{json.dumps({'token': tok})}'></script>")


def page_meta(data):
    """そのページの題（title / og:title）と説明を作る。

    2026-09-24まで、40ページ全部が同じ題と同じ説明を名乗っていた。
    Search Consoleが記録ページ24枚を「検出 - インデックス未登録」にしていたのは
    これが原因と思われる。Googleから見ると、同じことを名乗るページが
    24枚並んでいたことになる。中身が違うなら、名乗りも違わなければならない。

    title  … 検索結果に出る行。ゲーム名と日付を前に置く
    og:title … XやDiscordのカードの見出し。短く読ませる
    desc   … 検索結果の説明文。118字で切る
    """
    SITE_T = "ハヤリゲー"
    # 呼び出し側が決め打ちしたいときは meta_title / meta_og / meta_desc を渡す
    if data.get("meta_title"):
        return (data["meta_title"], data.get("meta_og") or data["meta_title"],
                (data.get("meta_desc") or "")[:118])

    date = str(data.get("date") or "")
    jp = f"{int(date[5:7])}月{int(date[8:10])}日" if len(date) >= 10 else ""
    col = data.get("column") or {}
    rows = data.get("ranking") or []
    tops = "・".join([r.get("game") for r in rows[:3] if r.get("game")])
    game = str(col.get("game") or "").strip()
    head = str(col.get("headline") or "").strip()

    if data.get("mode") == "archive":
        return (f"これまでの記録 ｜ {SITE_T}", "これまでの記録",
                "その日ふだんより配信が増えたゲームを、日ごとに残しています。"
                "VTuber・ゲーム実況者のYouTube配信の記録。")

    # トップページ。中身は「今日の記録ページ」と同じものだが、
    # 同じ題を名乗らせると、Googleから見て同じページが2枚になる。
    # トップは毎日中身が変わる「入口」なので、日付を入れない題にして、
    # 日付つきの題は /d/YYYY-MM-DD/ のほうに持たせる。
    if data.get("view") != "archive":
        lead = (f"注目は『{game}』── {head}" if game and head else "")
        return (f"{SITE_T} ｜ VTuber・ゲーム実況者がいま配信しているゲーム ランキング",
                f"{SITE_T} ｜「次に流行るゲーム」がわかるサイト",
                (f"YouTubeのゲーム配信を毎日数えています。{jp}は {tops} ほか。{lead}"
                 if tops else
                 "YouTubeのゲーム配信を毎日数えて、いま増えているゲームを出しています。")[:118])

    # 日ごとの記録ページ
    if not jp:
        return (f"{SITE_T} ｜ VTuber・ゲーム実況者がいま配信しているゲーム ランキング",
                f"{SITE_T} ｜「次に流行るゲーム」がわかるサイト",
                "YouTubeのゲーム配信を毎日数えて、いま増えているゲームを出しています。")
    title = (f"{jp}のゲーム配信ランキング ｜ {tops} ほか ｜ {SITE_T}" if tops
             else f"{jp}のゲーム配信ランキング ｜ {SITE_T}")
    if game and head:
        og = f"{jp}｜{game} — {head}"
        desc = f"{jp}、{tops} などが配信されていました。注目は『{game}』── {head}"
    else:
        og = f"{jp}のゲーム配信ランキング"
        desc = f"{jp}にVTuber・ゲーム実況者が配信していたゲーム。{tops} ほか。"
    return title, og, desc[:118]


def render_page(path, data, depth, site_url=""):
    """1ページ書き出す。depth はサイト直下から何階層下か。

    30日を過ぎた記録を作り直すときにも使うので、main() の中ではなく
    モジュールの直下に置いてある。
    """
    tpl = (SITE / "template.html").read_text(encoding="utf-8")
    d = dict(data, paths={"home": "../" * depth or "./",
                          "archive": ("../" * depth or "./") + "archive/"})
    # page_body はサーバー側で __PAGEBODY__ に入れるものなので、
    # ページのJSからは読まない。DATAに入れておくと同じHTMLが2回入って重くなるうえ、
    # 中に </script> があるとそこでDATAの読み込みが切れる（2026-09-25、
    # ゲーム検索のページを足したときに実際に壊れた）。
    d.pop("page_body", None)
    for k in ("meta_title", "meta_og", "meta_desc"):
        d.pop(k, None)
    p = SITE / path
    p.parent.mkdir(parents=True, exist_ok=True)
    home = "../" * depth or "./"
    # そのページ自身のURL。index.html は省いて、ディレクトリの形にする。
    page = "" if path == "index.html" else path.replace("index.html", "")
    rows_ = data.get("ranking") or []
    col_ = data.get("column")
    # まとめのカードはトップにだけ出す。過去の日のページには出さない
    mt = data.get("matome") if data.get("view") != "archive" else None
    title, ogtitle, desc = page_meta(data)
    # 共有ボタン。コラムのほうは「その日のページ」を指す。
    # トップを指すと、明日には別のコラムになってしまうため。
    share_site = share_html(
        "VTuber・ゲーム実況者がいま配信しているゲームのランキング #ハヤリゲー",
        f"{site_url}/" if site_url else "", "このサイトを共有") if site_url else ""
    share_col = ""
    col = data.get("column") or {}
    cdate = str(col.get("date") or data.get("date") or "")
    if site_url and col.get("game") and col.get("headline") and len(cdate) >= 10:
        share_col = share_html(
            f"{col['headline']}｜『{col['game']}』 #ハヤリゲー",
            f"{site_url}/d/{cdate}/", "このコラムを共有")
    # JSONの中に </script> や <!-- があると、HTMLの側が先に反応してしまう。
    # 文字列の中身は変えずに、その並びだけ崩しておく（JSONとしては同じ値になる）。
    blob = json.dumps(d, ensure_ascii=False).replace("</", "<\\/").replace("<!--", "<\\!--")
    p.write_text(tpl.replace("__DATA__", blob)
                    .replace("__TITLE__", e(title))
                    .replace("__OGTITLE__", e(ogtitle))
                    .replace("__DESC__", e(desc))
                    .replace("__HOME__", home)
                    .replace("__PAGEURL__", f"{site_url}/{page}" if site_url else "")
                    .replace("__SITE__", site_url)
                    # JavaScriptなしでも読める中身。JSが動けば同じ内容で描き直される
                    .replace("__PICKDISP__", "" if col_ else "display:none")
                    # JavaScriptなしでも、いつ書いたコラムかが分かるように
                    .replace("__PICKTITLE__", pick_title(col_, data))
                    .replace("__PICKNOTE__", pick_note(col_, data))
                    .replace("__SSR_PICK__", ssr_pick(col_))
                    .replace("__SSR_HOT__", ssr_hot(data.get("rising"),
                                                    data.get("view") == "archive"))
                    .replace("__SSR_NOTES__", ssr_notes(col_))
                    # 記録のページは過去の話なので「今」と書かない。
                    # JSが動く前にも正しい見出しが出るように、ここで入れておく。
                    .replace("__HOTTITLE__",
                             "この日アツかったゲーム"
                             if data.get("view") == "archive"
                             else "今このゲームがアツい！")
                    .replace("__SSR_ARCH__",
                             ssr_arch(data.get("archive"), home)
                             if data.get("mode") == "archive" else "")
                    # どの節を出すかは、これまでJavaScriptだけが決めていた。
                    # そのため「これまでの記録」「このサイトについて」「ゲームを探す」は、
                    # HTMLに中身が入っているのに display:none のまま隠れていた
                    # （2026-09-26に、記録の一覧をHTMLにも書き出して気づいた）。
                    # 最初から正しい状態で出す。JSが動けば同じ内容で描き直される。
                    .replace("__MAINDISP__",
                             "display:none"
                             if data.get("mode") in ("archive", "page", "admin") else "")
                    .replace("__ARCHDISP__",
                             "" if data.get("mode") == "archive" else "display:none")
                    .replace("__PAGEDISP__",
                             "" if data.get("mode") == "page" else "display:none")
                    .replace("__SSR_CARDS__", ssr_cards(rows_))
                    .replace("__SSR_ROWS__", ssr_rows(rows_))
                    .replace("__PAGEBODY__", data.get("page_body", ""))
                    .replace("__NAV__", nav_html(data, home))
                    .replace("__POINT__", POINT)
                    .replace("__NCH__", f"{watched_channels():,}")
                    .replace("__MTDISP__", "" if mt else "display:none")
                    .replace("__MTHREF__", home + (mt["href"] if mt else ""))
                    .replace("__SSR_MT__", ssr_matome(mt))
                    .replace("__SHARE_COL__", share_col)
                    .replace("__SHARE_SITE__", share_site)
                    .replace("__FOLLOW__", follow_html(read_json(
                        DATA / "site_config.json", {}) or {}))
                    .replace("__SNS__", sns_html(read_json(
                        DATA / "site_config.json", {}) or {}))
                    .replace("__ANALYTICS__", analytics_html())
                    # AdSenseの所有権確認タグ／広告タグ。貼られたものをそのまま出す
                    .replace("__HEADEXTRA__", head_extra(read_json(
                        DATA / "site_config.json", {}) or {})),
                 encoding="utf-8")


_NCH = []


def watched_channels():
    """毎日見に行っているチャンネル数。看板と説明ページに出すために数える。
    ページごとに数え直すと遅いので、一度数えたら覚えておく。"""
    if _NCH:
        return _NCH[0]
    chans = read_json(DATA / "channels_enriched.json", []) or []
    manual = read_json(DATA / "channels_manual.json", {}) or {}
    n = 0
    for c in chans:
        cid = c.get("channel_id")
        m = manual.get(cid)
        if m == "外す":
            continue
        if m != "残す" and str(c.get("auto", "")).startswith("外す"):
            continue
        n += 1
    _NCH.append(n)
    return n


# ------------------------------------------------------- 週・月のまとめ
# 毎日のコラムが「その日起きたこと」なのに対し、こちらは
# 1日では見えないことを書く読みもの。2026-09-14に、Xに流して消すのは
# もったいないという話になり、サイトにも残すことにした。
#
#   data/columns/weekly/YYYY-MM-DD.json   … その週の月曜の日付で置く
#   data/columns/monthly/YYYY-MM.json     … その月
#
# 形（週と月で同じ。週は section が1つ、月は3〜5つになる）:
#   {"title": "見出し", "lead": "リード（任意）",
#    "sections": [{"h": "小見出し（任意）", "body": "本文"}],
#    "sources": [{"t": "見出し", "u": "https://..."}]}
SPECIALS = [("weekly", "w", "週まとめ"), ("monthly", "m", "月まとめ")]


def special_key_label(kind, key):
    """ファイル名から、人が読む見出しを作る。"""
    if kind == "monthly":
        return f"{int(key[:4])}年{int(key[5:7])}月のまとめ"
    d = datetime.strptime(key, "%Y-%m-%d")
    end = d + timedelta(days=6)
    return (f"{d.year}年{d.month}月{d.day}日〜{end.month}月{end.day}日の週まとめ")


def load_specials():
    """週・月のまとめを読む。壊れているものは載せない。"""
    out = []
    for kind, slug, label in SPECIALS:
        d = DATA / "columns" / kind
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.json")):
            c = read_json(f, None)
            bad = check_special(c)
            if bad:
                log(f"まとめを載せません（{kind}/{f.name}）: {bad[0]}")
                continue
            out.append({"kind": kind, "slug": slug, "label": label,
                        "key": f.stem, "col": c,
                        "title": str(c.get("title", "")).strip(),
                        "heading": special_key_label(kind, f.stem)})
    out.sort(key=lambda x: (x["key"], x["kind"]), reverse=True)
    return out


def check_special(c):
    """まとめの形だけ見る。中身の言い回しは check_column.py 側と同じ考え方。"""
    if not isinstance(c, dict):
        return ["JSONの形が違います"]
    bad = []
    if not str(c.get("title", "")).strip():
        bad.append("title が空です")
    secs = c.get("sections")
    if not isinstance(secs, list) or not secs:
        bad.append("sections がありません")
    else:
        for i, sec in enumerate(secs, 1):
            if not isinstance(sec, dict) or not str(sec.get("body", "")).strip():
                bad.append(f"{i}番目の section に body がありません")
    text = " ".join(str(sec.get("body", "")) for sec in (secs or [])
                    if isinstance(sec, dict)) + str(c.get("lead", ""))
    for w in HEDGE:
        if w in text:
            bad.append(f"推測を含む言い回しがあります: 「{w}」")
    for src in (c.get("sources") or []):
        u = str((src or {}).get("u", ""))
        if not re.match(r"^https?://", u):
            bad.append(f"出典のURLが不正です: {u!r}")
        else:
            for ng in BAD_SOURCE:
                if ng in u.lower():
                    bad.append(f"まとめ・二次情報を出典にしています: {u}")
                    break
    return bad


YT_ID = re.compile(r"(?:youtube\.com/watch\?v=|youtu\.be/)([\w-]{11})")


def special_thumb(c):
    """まとめに載せる画像。YouTubeの動画URLからサムネイルを作る。

    JSONに "hero": {"u": "...", "by": "チャンネル名"} があればそれを使い、
    無ければ出典のYouTube動画から拾う。借りた相手（by）は必ず一緒に持ち回る。
    """
    hero = c.get("hero") or {}
    cands = [(hero.get("u", ""), hero.get("by", ""))]
    cands += [(str(s.get("u", "")), str(s.get("t", "")).split(" — ")[0])
              for s in (c.get("sources") or [])]
    for u, by in cands:
        m = YT_ID.search(str(u))
        if m:
            return {"th": f"https://i.ytimg.com/vi/{m.group(1)}/mqdefault.jpg", "by": by}
    return {"th": "", "by": ""}


def special_period_end(item):
    """その まとめ が扱っている期間の最終日。"""
    if item["kind"] == "monthly":
        y, m = int(item["key"][:4]), int(item["key"][5:7])
        nxt = datetime(y + (m == 12), (m % 12) + 1, 1)
        return nxt - timedelta(days=1)
    return datetime.strptime(item["key"], "%Y-%m-%d") + timedelta(days=6)


def latest_special(items, days=14):
    """トップに出す1本。期間が終わってから days 日までは出し続ける。

    「更新された日だけ」にすると、せっかく書いた読みものが翌日には
    どこからも見えなくなる。次のまとめが出るまでは置いておく。
    """
    now = datetime.now(JST).replace(tzinfo=None)
    fresh = [x for x in items
             if (now - special_period_end(x)).days <= days]
    if not fresh:
        return None
    x = max(fresh, key=lambda i: special_period_end(i))
    th = special_thumb(x["col"])
    return {"href": f'{x["slug"]}/{x["key"]}/', "label": x["label"],
            "title": x["title"], "heading": x["heading"],
            "th": th["th"], "by": th["by"]}


def ssr_matome(mt, home=""):
    """JavaScriptなしでも読めるように、同じカードをHTMLでも書いておく。"""
    if not mt:
        return ""
    img = (f'<img src="{e(mt["th"])}" alt="" loading="lazy">' if mt["th"] else "")
    by = f' ／ 画像 YouTube {e(mt["by"])}' if mt["by"] else ""
    return (f'{img}<div class="txt"><span class="kind">{e(mt["label"])}</span>'
            f'<div class="tt">{e(mt["title"])}</div>'
            f'<div class="sub">{e(mt["heading"])}{by}</div></div>')


def special_html(item):
    """まとめ1本ぶんの中身。"""
    c = item["col"]
    out = [f'<p class="when">{e(item["heading"])}</p>',
           f'<h1>{e(c.get("title"))}</h1>']
    th = special_thumb(c)
    if th["th"]:
        out.append(f'<figure class="dochero"><img src="{e(th["th"])}" alt="" loading="lazy">'
                   f'<figcaption>YouTube ／ {e(th["by"])}</figcaption></figure>')
    if str(c.get("lead", "")).strip():
        out.append(f'<p class="lead">{e(c["lead"])}</p>')
    for sec in c.get("sections") or []:
        if str(sec.get("h", "")).strip():
            out.append(f'<h2>{e(sec["h"])}</h2>')
        for para in str(sec.get("body", "")).split("\n"):
            if para.strip():
                out.append(f"<p>{e(para.strip())}</p>")
    srcs = c.get("sources") or []
    if srcs:
        out.append("<h2>出典</h2><ul>")
        out += [f'<li><a href="{e(s.get("u"))}" target="_blank" '
                f'rel="noopener">{e(s.get("t") or s.get("u"))}</a></li>' for s in srcs]
        out.append("</ul>")
    return "\n".join(out)


def specials_index_html(items):
    """まとめの一覧ページ。"""
    if not items:
        return ("<h1>週・月のまとめ</h1>"
                "<p>まだありません。毎週月曜と毎月1日に追加していきます。</p>")
    out = ["<h1>週・月のまとめ</h1>",
           "<p>毎日のコラムが「その日起きたこと」なのに対して、ここでは"
           "1日を見ているだけでは分からないことを書いています。</p>"]
    for kind, slug, label in SPECIALS:
        rows = [x for x in items if x["kind"] == kind]
        if not rows:
            continue
        out.append(f"<h2>{e(label)}</h2><ul>")
        for x in rows:
            out.append(f'<li><a href="../{x["slug"]}/{e(x["key"])}/">'
                       f'{e(x["title"])}</a>'
                       f'<br><small>{e(x["heading"])}</small></li>')
        out.append("</ul>")
    return "\n".join(out)


def sns_html(cfg):
    """フッターに出す、ハヤリゲー自身のSNSへのリンク。

    data/site_config.json の bluesky_handle / x_handle に書いたものだけ出す。
    空なら出さない。Xのユーザー名が決まってからコードを直さずに済むように、
    設定ファイル側で持たせている。

    サイトとアカウントを相互にリンクしておくと、片方を見つけた人が
    もう片方にたどり着ける。Blueskyはハンドルが hayarige.com なので、
    ドメインを持っていること自体が本人証明にもなる。
    """
    out = []
    bs = str(cfg.get("bluesky_handle") or "").strip().lstrip("@")
    xh = str(cfg.get("x_handle") or "").strip().lstrip("@")
    if bs:
        out.append(f'<a class="flink" href="https://bsky.app/profile/{e(bs)}" '
                   f'target="_blank" rel="noopener me">Bluesky</a>')
    if xh:
        out.append(f'<a class="flink" href="https://x.com/{e(xh)}" '
                   f'target="_blank" rel="noopener me">X</a>')
    return "".join(out)


# 共有ボタンと公式アカウントのボタンに付ける印。
# 各社のロゴをそのまま描き写すと、細部が違ったときに「偽物のロゴ」になる。
# ここでは、どのサービスかが分かる程度の簡単な形にとどめて、
# 見分けは色と名前（X / Bluesky / LINE）でつけている。
ICON_X = ('<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18.244 2.25h3.308'
          'l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 '
          '2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>')
ICON_BS = ('<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5.77 3.44C8.34 5.37 '
           '11.1 9.28 12 11.38c.9-2.1 3.66-6.01 6.23-7.94C20.08 2.05 23 .96 23 4.29c0 '
           '.67-.38 5.6-.6 6.4-.78 2.78-3.62 3.49-6.14 3.06 4.41.75 5.53 3.23 3.11 5.72'
           '-4.6 4.72-6.61-1.19-7.13-2.7-.09-.28-.14-.41-.14-.3 0-.11-.05.02-.14.3-.52 '
           '1.51-2.53 7.42-7.13 2.7-2.42-2.49-1.3-4.97 3.11-5.72-2.52.43-5.36-.28-6.14'
           '-3.06C.98 9.89.6 4.96.6 4.29.6.96 3.52 2.05 5.37 3.44Z"/></svg>')
ICON_HB = ('<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4.6 3.2h3.6c1.7 0 '
           '2.9.3 3.7.9.8.6 1.2 1.5 1.2 2.7 0 .7-.2 1.3-.5 1.8-.3.5-.8.9-1.4 1.1.8.2 '
           '1.4.6 1.8 1.2.4.6.6 1.3.6 2.2 0 1.3-.4 2.3-1.3 3-.9.7-2.1 1-3.7 1H4.6V3.2Zm3.4 '
           '5.6c.7 0 1.2-.1 1.5-.4.3-.3.5-.7.5-1.2s-.2-.9-.5-1.2c-.4-.2-.9-.4-1.6-.4h-.8v3.2'
           'h.9Zm.2 5.9c.8 0 1.3-.1 1.7-.4.4-.3.6-.8.6-1.4 0-.6-.2-1-.6-1.3-.4-.3-1-.4-1.8-.4'
           'h-1v3.5h1.1ZM17.5 14.1c.6 0 1.1.2 1.5.6.4.4.6.9.6 1.5s-.2 1.1-.6 1.5c-.4.4-.9.6'
           '-1.5.6s-1.1-.2-1.5-.6a2 2 0 0 1-.6-1.5c0-.6.2-1.1.6-1.5.4-.4.9-.6 1.5-.6Zm1.3-1.4'
           'h-2.5V3.2h2.5v9.5Z"/></svg>')
ICON_LN = ('<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2.4c5.51 0 10 3.63 '
           '10 8.1 0 1.78-.7 3.39-2.22 4.98-2.2 2.53-7.12 5.62-8.24 6.09-1.07.45-.94-.29'
           '-.9-.55l.15-.88c.03-.27.07-.68-.03-.94-.11-.29-.57-.44-.9-.51C5 18.03 1.99 '
           '14.8 1.99 10.5c0-4.47 4.5-8.1 10.01-8.1ZM8.2 8.2H6.78c-.22 0-.4.18-.4.39v4.8'
           'c0 .22.18.39.4.39h2.96c.22 0 .4-.17.4-.39v-.72c0-.21-.18-.39-.4-.39H7.97V8.59'
           'c0-.21-.17-.39-.39-.39Zm3.24 0h-.72c-.22 0-.39.18-.39.39v4.8c0 .22.17.39.39.39'
           'h.72c.22 0 .4-.17.4-.39v-4.8c0-.21-.18-.39-.4-.39Zm5.35 0h-.72c-.22 0-.4.18-.4'
           '.39v2.85L13.47 8.4a.4.4 0 0 0-.32-.2h-.76c-.22 0-.4.18-.4.39v4.8c0 .22.18.39.4'
           '.39h.72c.22 0 .4-.17.4-.39v-2.85l2.2 2.97c.07.1.19.16.31.16h.77c.22 0 .39-.17'
           '.39-.39v-4.8c0-.21-.17-.39-.39-.39Zm4.02 0h-2.96c-.22 0-.4.18-.4.39v4.8c0 .22'
           '.18.39.4.39h2.96c.22 0 .39-.17.39-.39v-.72c0-.21-.17-.39-.39-.39h-1.85v-.72h1.85'
           'c.22 0 .39-.17.39-.39v-.72c0-.22-.17-.39-.39-.39h-1.85V9.7h1.85c.22 0 .39-.17'
           '.39-.39v-.72c0-.21-.17-.39-.39-.39Z"/></svg>')


def follow_html(cfg):
    """ハヤリゲー自身のSNSへのリンク。共有ボタンとは役割が違うので分けてある。

    共有ボタン … 読んだ人が「これを広める」ためのもの
    こちら     … 読んだ人が「次からも追う」ためのもの
    混ぜると、どちらのつもりで押したのかが分からなくなる。

    ハンドルは data/site_config.json から読む（bluesky_handle / x_handle）。
    空のものは出さない。
    """
    bs = str(cfg.get("bluesky_handle") or "").strip().lstrip("@")
    xh = str(cfg.get("x_handle") or "").strip().lstrip("@")
    if not (bs or xh):
        return ""
    out = ['<div class="follow"><span class="fl-l">ハヤリゲーの更新を受け取る</span>']
    if xh:
        out.append(f'<a class="f-x" href="https://x.com/{e(xh)}" target="_blank" '
                   f'rel="noopener me">{ICON_X}Xでフォロー</a>')
    if bs:
        out.append(f'<a class="f-bs" href="https://bsky.app/profile/{e(bs)}" '
                   f'target="_blank" rel="noopener me">{ICON_BS}Blueskyでフォロー</a>')
    return "".join(out) + "</div>"


def share_html(text, url, label):
    """共有ボタン。外部のスクリプトは1行も使わない。ただのリンクにする。

    ボタンの正体はどのサービスも「本文とURLを載せた投稿画面を開くURL」なので、
    JavaScriptを読み込む必要がない。外部スクリプトを貼ると、そのぶん
    ページが重くなるうえ、読者がどのページを見たかが相手に伝わる。
    このサイトは「Cookieを置かず、閲覧者を個人として追跡しない」と
    説明ページに書いてある。書いたことは守る。

    URLの形は各社の公式ドキュメントで確かめた（2026-09-24）。
      X       https://x.com/intent/post?text=&url=
      Bluesky https://bsky.app/intent/compose?text=   ※urlの項目が無い。本文に含める
      LINE    https://social-plugins.line.me/lineit/share?url=&text=
      はてブ  https://b.hatena.ne.jp/entry/ + ページのURL

    はてなブックマークの公式のボタンはJavaScriptを読み込む形だが、
    それが足すのは「何人がブックマークしたか」の吹き出しだけで、
    リンク自体（上の形）はスクリプト無しでそのまま動く。
    色 #00A4DE ははてな公式のブランドページに載っている値。
    """
    def q(v):
        # / も含めて全部エスケープする。クエリの中に生の / を残すと、
        # 受け取る側の実装によっては途中で切られることがある。
        return urllib.parse.quote(v, safe="")
    x = f"https://x.com/intent/post?text={q(text)}&url={q(url)}"
    bs = f"https://bsky.app/intent/compose?text={q(text + chr(10) + url)}"
    ln = f"https://social-plugins.line.me/lineit/share?url={q(url)}&text={q(text)}"
    # はてブだけURLを素のまま置く（公式のボタンがこの形）
    hb = "https://b.hatena.ne.jp/entry/" + url
    btn = ('<a class="sh sh-{k}" href="{u}" target="_blank" '
           'rel="noopener nofollow">{i}{n}</a>')
    return ('<div class="share"><span class="sh-l">' + e(label) + "</span>"
            + btn.format(k="x", u=e(x), n="X", i=ICON_X)
            + btn.format(k="bs", u=e(bs), n="Bluesky", i=ICON_BS)
            + btn.format(k="ln", u=e(ln), n="LINE", i=ICON_LN)
            + btn.format(k="hb", u=e(hb), n="はてブ", i=ICON_HB)
            + "</div>")


# ---------------------------------------------------------------- 広告（AdSense）
# 2026-09-26 たろちんさんと相談して入れた。順番は「申請の下ごしらえ → 申請 →
# 通ったら広告を出す」で、**そのどの段階にいるかを data/site_config.json の
# "ads" 1語で切り替える。**
#
# なぜ1語にしたか: このサイトは説明ページに「Cookieを置かず、閲覧者を個人として
# 追跡しない」と書いてある。広告を出せばそれは嘘になる。かといって、まだ広告が
# 無いうちから「Google広告のCookieを使っています」と書くのも嘘である。
# **書いてあることと動いているものが食い違うのが、いちばん損をする。**
# 文面をひとつの印に紐づけておけば、切り替えを忘れられない。
#
# Googleが求めている開示（support.google.com/adsense/answer/1348695 で確認）
#   ・第三者配信事業者（Googleを含む）がCookieを使って広告を配信すること
#   ・Cookieによって、過去のアクセス情報に基づく広告が表示されること
#   ・利用者が広告設定で パーソナライズ広告を無効にできること
# 下の ADS_ON の文面は、この3つをそのまま日本語にしたもの。

ADS_NONE, ADS_PENDING, ADS_ON = "none", "申請中", "掲載中"


def ads_mode(cfg):
    m = str((cfg or {}).get("ads") or ADS_NONE).strip()
    return m if m in (ADS_NONE, ADS_PENDING, ADS_ON) else ADS_NONE


def head_extra(cfg):
    """AdSenseの管理画面から渡されるタグを、そのまま <head> に入れる。

    所有権の確認に使うメタタグと、広告を出すためのスクリプトの両方が
    ここを通る。どちらも文面はGoogleが指定するので、こちらで組み立てず
    「貼られたものをそのまま出す」形にしてある。
    まちがって本文やスタイルを貼っても事故らないよう、<meta> と <script> の
    行だけ通す。
    """
    raw = str((cfg or {}).get("adsense_head") or "").strip()
    if not raw:
        return ""
    ok = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    for ln in ok:
        if not re.fullmatch(r"<(meta|script)\b[^<>]*>(</script>)?", ln):
            log(f"site_config.json の adsense_head に、そのまま出せない行が"
                f"ありました（無視します）: {ln[:60]}")
            return ""
    return "".join(ok)


def ads_txt(cfg):
    """ads.txt の中身。AdSenseのサイトIDを入れると出る。

    必須ではないが、Googleが「入れることを強く推奨」している
    （support.google.com/adsense/answer/12171612 で確認）。
    自分の広告枠を売ってよい相手を宣言するファイルで、なりすましを防ぐ。
    """
    pid = str((cfg or {}).get("adsense_pub_id") or "").strip()
    if not re.fullmatch(r"pub-\d{10,20}", pid):
        return ""
    return f"google.com, {pid}, DIRECT, f08c47fec0942fa0\n"


def ads_privacy_html(cfg):
    """プライバシーのページに出す、広告についての説明。"""
    m = ads_mode(cfg)
    if m == ADS_NONE:
        return ""
    if m == ADS_PENDING:
        return """
<h2>広告について</h2>
<p>当サイトは現在、Google AdSense による広告の掲載を申請しています。
<b>この文章を書いている時点では、広告は表示していません。</b>
審査を通って広告を出し始めたときは、このページを同時に書き換え、
どのCookieが使われるかをここに明記します。</p>
"""
    return """
<h2>広告について</h2>
<p>当サイトは第三者配信の広告サービス <b>Google AdSense</b> を利用しています。</p>
<p>第三者配信事業者（Googleを含む）は、Cookie を使用して、
利用者が過去に当サイトや他のサイトへアクセスした情報にもとづく広告を配信します。
Google が広告 Cookie を使用することにより、Google やそのパートナーは、
当サイトや他のサイトへのアクセス情報にもとづく広告を利用者に表示できます。</p>
<p>パーソナライズ広告は、
<a href="https://www.google.com/settings/ads" target="_blank" rel="noopener">広告設定</a>
で無効にできます。第三者配信事業者による Cookie の使用を無効にする方法は
<a href="https://www.aboutads.info/choices/" target="_blank" rel="noopener">www.aboutads.info</a>
をご覧ください。</p>
<p>広告の内容は配信事業者が決めており、当サイトが選んでいるものではありません。
ランキングの順位や、コラムで取り上げるゲームの選び方は、
広告とは一切関係ありません。</p>
"""


def privacy_html(cfg):
    """プライバシーと問い合わせ先。広告や解析を入れるなら要るページ。

    いま出している内容は、実際にやっていることだけ。将来AdSenseなどを
    入れたら、ここと説明ページの「Cookieを置かず」の一文を必ず直すこと。
    書いてあることと動いているものが食い違うのが、いちばん損をする。
    """
    mail = str(cfg.get("contact_email") or "").strip()
    mail_html = (f'<p><a href="mailto:{e(mail)}">{e(mail)}</a></p>'
                 if mail else
                 "<p>準備中です。</p>")
    return f"""
<h2>お問い合わせ</h2>
<p class="lead">数字の間違い、ゲーム名の取り違え、掲載についてのご相談など、
こちらへお願いします。</p>
{mail_html}
<p>配信者・権利者の方へ。当サイトの集計に含めてほしくない場合や、
コラムでの紹介について気になる点がある場合も、同じ窓口へご連絡ください。
確認のうえ対応します。</p>

<h2>アクセス解析について</h2>
<p>ページの閲覧数を知るために <b>Cloudflare Web Analytics</b> を使っています。
このしくみは <b>Cookieを置きません</b>。閲覧者を個人として識別したり、
サイトをまたいで追いかけたりすることもありません。
分かるのは「どのページが何回見られたか」「どこから来たか」といった
まとまった数字だけです。</p>
{ads_privacy_html(cfg)}
<h2>外部のサイトへのリンク</h2>
<p>ランキングやコラムから、SteamやAmazonの商品ページへリンクしています。
このうちAmazonへのリンクには紹介料の識別子が付いています。
Amazonのアソシエイトとして、当サイトは適格販売により収入を得ています。</p>
<p>リンク先での購入や登録について、当サイトは責任を負いません。
リンク先のプライバシーの扱いは、それぞれのサイトの方針に従います。</p>

<h2>集めているデータについて</h2>
<p>当サイトはYouTubeのAPIを使って、公開されている配信・動画の
タイトル・チャンネル名・再生数を取得しています。
<b>配信タイトルとチャンネル名は30日で削除しています</b>
（YouTubeの開発者ポリシーに沿った運用です）。
30日を過ぎた日の記録に残るのは、こちらで数えた「どのゲームが何件」という
集計値だけで、元のタイトルは残していません。</p>
<p>当サイトはYouTube APIサービスを利用しています。利用にあたっては
<a href="https://www.youtube.com/t/terms" target="_blank" rel="noopener">YouTube利用規約</a>および
<a href="https://policies.google.com/privacy" target="_blank" rel="noopener">Googleプライバシーポリシー</a>
が適用されます。</p>

<h2>免責</h2>
<p>掲載している数字は、当サイトが登録しているチャンネルの範囲で数えたものです。
日本のゲーム配信のすべてではありません。判定の誤りや取りこぼしもあります。
気づいたものは直していますが、内容の正確性を保証するものではありません。</p>
"""


# ---------------------------------------------------------------- ゲームを探す
# 「このゲーム、前はいつランキングに入っていた？」に答えるための索引。
# （2026-09-25 利用者からの要望）
#
# 中身はゲーム名・日付・件数・チャンネル数だけ。**配信タイトルもチャンネル名も
# 入れない。** あれはYouTubeから借りた文字で、30日で消す約束になっている。
# ここに入れると、その約束を破ることになる。
# こちらが数えた集計値は、公開してよいと開発者ポリシーが明示している。
#
# 32日ぶんで10KB。1年ぶんでも0.1MB程度なので、まるごと読み込んで
# 手元で絞り込める。サーバー側の仕掛けは要らない。

GAME_DAYS_MIN = 2      # その日2チャンネル以上が配信したものだけ残す

def day_games(rows):
    """その日の全ゲームを {ゲーム名: [件数, チャンネル数]} にする。

    ランキングのページに残しているのは上位30件まで。だが、このサイトが
    見つけたいのは**まだ小さいゲーム**のほうで、そちらは30位に入らない。
    実際『Feign』は29日間・のべ7チャンネルが配信していたのに、
    一度もランキングに入っていない（2026-09-25、検索を作って気づいた）。

    元になる日別ファイルは30日で消える（YouTubeの規約）。
    **今日ぶんを今日のうちに残しておかないと、あとから作れない。**
    残すのは「どのゲームが何件あったか」という、こちらが数えた集計値だけ。
    配信タイトルもチャンネル名も入れない。
    """
    return {r["game"]: [r["videos"], r["channels"]] for r in rows
            if r.get("channels", 0) >= GAME_DAYS_MIN}


def search_index():
    """site/search.json を書く。

    元にするのは記録ページ（site/d/*/index.html）そのもの。
    その日作り直したぶんだけを見ると、作り直しが走らなかった日が抜ける。
    ページは全期間ぶん残っているので、そちらから読むほうが確実。
    """
    gdays = read_json(DATA / "game_days.json", {}) or {}
    dd = sorted(d.name for d in (SITE / "d").iterdir()
                if d.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d.name)) \
        if (SITE / "d").is_dir() else []
    at = {d: i for i, d in enumerate(dd)}
    rows = {}
    for day in dd:
        f = SITE / "d" / day / "index.html"
        try:
            h = f.read_text(encoding="utf-8")
            i = h.index("const DATA = ") + len("const DATA = ")
            obj, _ = json.JSONDecoder().raw_decode(h[i:])
        except (ValueError, OSError):
            continue
        rank = {r["game"] for r in obj.get("ranking", [])}
        # その日の全ゲーム（記録があればそちら、無ければ上位30件だけ）
        src = gdays.get(day) or {r["game"]: [r.get("videos", 0), r.get("channels", 0)]
                                 for r in obj.get("ranking", [])}
        for name, (v, c) in src.items():
            g = rows.setdefault(name, {"n": name, "d": [], "v": [], "c": [], "r": []})
            g["d"].append(at[day])
            g["v"].append(v)
            g["c"].append(c)
            if name in rank:
                g["r"].append(at[day])          # ランキングに入った日

    # コラムで取り上げた日。コラムはこちらが書いたものなので、全期間残っている。
    cd = DATA / "columns"
    for f in sorted(cd.glob("*.json")) if cd.is_dir() else []:
        day = f.stem
        if day not in at:
            continue
        c = read_json(f, None) or {}
        if c.get("game"):
            g = rows.setdefault(c["game"], {"n": c["game"], "d": [], "v": [], "c": []})
            g.setdefault("col", []).append({"i": at[day],
                                            "h": str(c.get("headline", ""))})

    # 検索用のキー。手で登録した別名とIGDBの別名を、詰めた形で並べる。
    # 「マイクラ」と打って Minecraft に当たるのは、ここに入れているから。
    al = read_json(DATA / "aliases.json", {}) or {}
    cat = {}
    try:
        for x in M.catalogue():
            cat[x["name"]] = [x.get("jp")] + list(x.get("alias") or [])
    except Exception as err:
        log(f"IGDBの別名を検索キーに入れられませんでした: {err}")
    for name, g in rows.items():
        keys = {M.compact(name)}
        for nm in list(al.get(name) or []) + [x for x in cat.get(name) or [] if x]:
            k = M.compact(str(nm))
            if k:
                keys.add(k)
        g["k"] = " ".join(sorted(keys))
        g["col"] = sorted(g.get("col", []), key=lambda x: x["i"])

    out = {"days": dd,
           "g": sorted(rows.values(), key=lambda x: (-len(x["d"]), x["n"]))}
    write_json(SITE / "search.json", out)
    size = (SITE / "search.json").stat().st_size
    log(f"ゲームの索引を書き出しました: {len(out['g'])} 種 / "
        f"{len(dd)} 日分 / {size // 1024} KB")


def search_html(home):
    """ゲームを探すページ。索引を読み込んで、手元で絞り込む。"""
    return """
<h2>ゲームを探す</h2>
<p class="lead">ゲーム名を入れると、そのゲームが<b>いつランキングに入っていたか</b>、
<b>コラムで取り上げた日があるか</b>が出ます。略称でも探せます（「マイクラ」など）。</p>
<div class="sbox">
  <input id="q" type="search" placeholder="ゲーム名を入力（例: マイクラ、スト6、ゴエモン）"
         autocomplete="off" autocapitalize="off" spellcheck="false">
</div>
<p id="shint" class="shint">読み込んでいます…</p>
<p class="slegend"><span class="sday">日付</span>数えた日
  <span class="sday rk">日付</span>ランキング入り
  <span class="sday col">日付</span>コラムで取り上げた日</p>
<div id="sres" class="sres"></div>
<script>
(function(){
  var HOME = "__H__";
  // match.py の compact() と同じ詰め方。全角半角をそろえ、記号と長音を落とす。
  var STRIP = /[\s・:：\-–—ー_'’‘"“”,、.。!！?？~〜/／|｜&＆#＃*＊+＋%％@＠^…♪♡★☆→←※=＝]/g;
  function cp(s){ return String(s||'').normalize('NFKC').toLowerCase().replace(STRIP,''); }
  function esc(s){ return String(s==null?'':s).replace(/[&<>"]/g,
    function(c){ return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }
  var IX = null, q = document.getElementById('q'),
      hint = document.getElementById('shint'), res = document.getElementById('sres');
  fetch(HOME + 'search.json').then(function(r){ return r.json(); }).then(function(j){
    IX = j;
    hint.textContent = j.g.length.toLocaleString() + '種のゲーム、'
      + j.days.length + '日分の記録から探します。';
    if (q.value) run();
    var h = decodeURIComponent((location.hash||'').replace(/^#/,''));
    if (h){ q.value = h; run(); }
  }).catch(function(){ hint.textContent = '索引を読み込めませんでした。'; });

  function card(g){
    var dd = g.d.map(function(i){ return IX.days[i]; });
    var last = dd[dd.length-1], first = dd[0];
    var cols = {}; (g.col||[]).forEach(function(c){ cols[IX.days[c.i]] = c.h; });
    var peak = 0, peakDay = '';
    g.c.forEach(function(v, n){ if (v > peak){ peak = v; peakDay = dd[n]; } });
    var rank = {}; (g.r||[]).forEach(function(i){ rank[IX.days[i]] = 1; });
    var chips = g.d.map(function(i, n){
      var d = IX.days[i], isCol = cols[d] != null, isR = rank[d] === 1;
      return '<a class="sday' + (isCol ? ' col' : (isR ? ' rk' : '')) + '"'
        + ' href="' + HOME + 'd/' + d + '/"'
        + ' title="' + esc(d + ' ／ ' + g.v[n] + '件 ' + g.c[n] + 'チャンネル'
            + (isR ? ' ／ ランキング入り' : '')
            + (isCol ? ' ／ コラム: ' + cols[d] : '')) + '">'
        + d.slice(5).replace('-', '/') + '</a>';
    }).join('');
    var colList = (g.col||[]).slice().reverse().map(function(c){
      return '<a class="scol" href="' + HOME + 'd/' + IX.days[c.i] + '/">'
        + '<span class="sd">' + IX.days[c.i] + '</span>' + esc(c.h) + '</a>';
    }).join('');
    return '<article class="scard"><h3>' + esc(g.n) + '</h3>'
      + '<div class="smeta">'
      + '<span><i>' + g.d.length + '</i>日、配信が数えられました</span>'
      + ((g.r||[]).length
          ? '<span>うち<i>' + g.r.length + '</i>日はランキング入り</span>'
          : '<span class="nork">ランキング（上位30）には入っていません</span>')
      + '<span>はじめて <i>' + first + '</i></span>'
      + '<span>直近 <i>' + last + '</i></span>'
      + '<span>最多 <i>' + peakDay + '</i>（' + peak + 'チャンネル）</span>'
      + '</div>'
      + (colList ? '<div class="scols"><b>コラムで取り上げた日</b>' + colList + '</div>' : '')
      + '<div class="sdays">' + chips + '</div></article>';
  }

  function run(){
    if (!IX) return;
    var v = cp(q.value);
    if (!v){ res.innerHTML = ''; return; }
    var hit = IX.g.filter(function(g){ return (g.k||'').indexOf(v) >= 0; });
    // 名前そのものが前から一致するものを上に
    hit.sort(function(a, b){
      var pa = cp(a.n).indexOf(v) === 0 ? 0 : 1, pb = cp(b.n).indexOf(v) === 0 ? 0 : 1;
      return pa - pb || b.d.length - a.d.length;
    });
    res.innerHTML = hit.length
      ? hit.slice(0, 40).map(card).join('')
        + (hit.length > 40 ? '<p class="shint">ほか ' + (hit.length - 40) + '件。'
            + 'もう少し詳しく入れてください。</p>' : '')
      : '<div class="empty">「' + esc(q.value) + '」に当たるゲームは、'
        + '記録の中にありませんでした。<br>'
        + '<span style="font-size:12.5px">'
        + '記録が残っているのは ' + IX.days[0] + ' から。'
        + 'それ以前のことは分かりません。</span></div>';
  }
  var t; q.addEventListener('input', function(){ clearTimeout(t); t = setTimeout(run, 120); });
})();
</script>
""".replace("__H__", home)


def about_html(cfg, n_channels):
    """このサイトについて。数字の出どころと、数えていないものを書く。"""
    lo = int(cfg.get("min_subscribers") or 0)
    jp = float(cfg.get("min_japanese_ratio", 0.5))
    return f"""
<h2>このサイトは何か</h2>
<p class="lead">VTuber・ゲーム実況者がYouTubeに出している配信のタイトルを毎日集めて、
いまどのゲームが配信されているかをランキングにしています。
「次に流行るゲームを早く見つけたい」人のために作りました。
配信する側にとっては次のネタ探しに、見る側にとっては「あのゲーム、急にみんなやってる」の答え合わせになります。</p>
<p>再生数の多い<b>動画</b>を並べるサイトはすでにたくさんあります。このサイトが並べるのは
<b>ゲーム</b>です。誰の動画が伸びたかではなく、どのゲームに人が集まっているかを見ます。</p>

<h2>どこから集めているか</h2>
<dl>
  <dt>対象</dt><dd>日本語で配信しているVTuber・ゲーム実況者のYouTubeチャンネル、現在 {n_channels:,} 件</dd>
  <dt>範囲</dt><dd>直近24時間に公開された配信・動画</dd>
  <dt>更新</dt><dd>1日2回（日本時間 7時ごろ / 19時ごろ）</dd>
  <dt>判定</dt><dd>配信タイトルの文字列から、約5万本のゲーム名辞書と照合しています</dd>
</dl>
<p>チャンネルは、登録者数 {lo:,} 人以上・1年以内に投稿がある・ゲームの動画を出している、
という条件で自動的に選んでいます。直近の動画タイトルにひらがな・カタカナが
{jp:.0%} 以上出てくるかどうかも見ていて、これを下回るチャンネルは外しています。
日本語圏の視聴者が見ている配信の流行を出すサイトなので、所属ではなく
実際に使っている言語で判断しています。</p>
<p>ゲームを作っている会社が運営する公式チャンネルは、数に入れていません。
新キャラのPVや生放送は、配信者がそのゲームを選んだという話ではないためです。
2026-09-18に調べたところ、あるゲームでは再生数の99%が会社の公式チャンネル1つから
出ていました。そのままだと「宣伝を打った日に流行している」と出てしまいます。</p>

<h2>どう数えているか</h2>
<p>順位は、次の3つを合わせた独自のスコアで決めています。</p>
<ul>
  <li><b>配信者数</b> ── そのゲームを配信したチャンネルが何件あったか</li>
  <li><b>再生数</b> ── その合計</li>
  <li><b>配信数</b> ── 配信・動画が何本あったか</li>
</ul>
<p>ひとりがたくさん投稿しただけで上位に来ないよう、<b>何人が配信したか</b>をいちばん重く見ています。
そのうえで、<b>同じ人が同じゲームを1日に何本も出した場合、2本目からは半分として数えています</b>
（再生数も同じで、その人のいちばん伸びた1本を丸ごと、残りを半分として足します）。
毎日おなじ顔ぶれが同じゲームを何本も上げると、その人ひとりで順位が積み上がってしまうためです。
「◯件」として出している数は、この割引をしたあとの数です。</p>
<p><b>「今このゲームがアツい」は、このサイトでいちばん見てほしい欄です。</b>
直近数日の平均とくらべて配信が増えたタイトルを、<b>倍率の大きい順</b>に6つ出しています。
倍率で並べると、ふだん誰も配信していない小さなゲームが上に来ます。それが狙いです。
まだ名前の知られていないゲームを見つけて、自分の配信で試してほしくて作った欄だからです。
大きな企画が立った日には、大きなゲームもここに入ってきます。
<b>3チャンネル以上が同じ日に別々に配信していること</b>を条件にしているので、
ひとりの思いつきは出てきません。倍率だけでは大きさが分からないので、
実数（ふだん◯件 → 今日◯件）と、何人が配信したかも並べています。</p>

<h2>この数字は誰が作ったものか</h2>
<p><b>ゲーム名の判定も、件数も、倍率も、すべて当サイトが独自に作った数字です。</b>
YouTubeが提供している数値や分類ではありません。</p>
<ul>
  <li><b>ゲーム名</b> ── 配信のタイトルを当サイトの辞書と照らし合わせて判定しています。
      YouTubeが動画に付けている分類とは別のもので、置き換えるものでもありません</li>
  <li><b>件数・チャンネル数・倍率</b> ── YouTubeのAPIから取れる公開情報を、
      当サイトが数え上げたものです</li>
  <li><b>再生数</b> ── これはYouTubeが返す数字そのものです。取得した時点の値なので、
      いま見ている数と差があることがあります</li>
</ul>
<p>判定を間違えていることもあります。気づいたものは直しています。
おかしな点を見つけたら<a href="../privacy/">お問い合わせ</a>からお知らせください。</p>

<h2>数えていないもの</h2>
<ul>
  <li><b>Shorts</b>（3分以下の動画）── YouTubeは縦向きで3分以内の動画を
      Shortsとして扱うため、それに合わせています</li>
  <li><b>切り抜き</b>（タイトルや チャンネル名から判定）</li>
  <li><b>同時視聴</b> ── アニメ・映画・発表会を視聴者と一緒に見る配信。
      ゲームを遊んでいる配信ではないので数えません</li>
  <li><b>同じ配信者が同じ日に出した続きもの</b> ── 1本の配信を分割した動画などは1件として数えます。
      別の日に続くシリーズは、その日ごとに数えます</li>
  <li><b>日本語以外で配信しているチャンネル</b> ── 事務所は問いません</li>
  <li><b>ゲーム名を判定できなかった配信</b> ── 推測では埋めません</li>
</ul>
<p>ただし、大会や企画の配信は題名がハッシュタグだけになりがちです
（「【#にじ遊戯王祭2026】対抗戦」など）。そういう配信は、<b>同じタグを使っている
ほかの人がゲーム名を書いていれば、そちらから判定しています</b>。
3人以上が使っているタグで、ゲーム名の分かる配信が3本以上あり、
その8割以上が同じゲームを指しているときだけです。
推測ではなく、同じ企画の中に答えが書いてある場合にかぎります。</p>

<h2>コラムについて</h2>
<p>「今日の注目ゲーム」は、数字が動いた理由を書いています。書くときのルールを決めていて、
<b>裏が取れないことは書きません</b>。根拠には、公式の発表・ゲームメディア・実際の配信そのものを
当たっています。説明できることが何も無い日は、その日は書きません。</p>

<h2>間違いを見つけたら</h2>
<p>ゲーム名の判定は自動なので、間違えることがあります。見つけしだい直しています。
おかしなものを見つけたら、<a href="https://x.com/tarochinko" target="_blank" rel="noopener">X（@tarochinko）</a>
のDMで教えてください。</p>

<h2>作っている人</h2>
<p>ゲーム実況者の たろちん（<a href="https://x.com/tarochinko" target="_blank" rel="noopener">@tarochinko</a>）が
個人で作っています。データはYouTube Data API、ゲーム名の辞書はIGDBを使っています。</p>
<p>このサイトはAmazonアソシエイト・プログラムの参加者です。商品ページへのリンクから
購入があった場合、紹介料を受け取ることがあります。ランキングの順位は
配信の数字だけで決めていて、紹介料は関係しません。</p>

<h2>アクセス解析について</h2>
<p>どのページがどれくらい見られているかを知るために、Cloudflare Web Analytics を
使っています。<b>この解析は</b>Cookieを置かず、閲覧者を個人として追いかけません。
このサイトが名前・メールアドレスなどの個人情報を集めることはありません。</p>
{"" if ads_mode(cfg) != ADS_ON else
 '<p>ただし、当サイトは Google AdSense による広告を掲載しており、'
 '<b>広告の配信にはCookieが使われます。</b>くわしくは'
 '<a href="../privacy/">お問い合わせ・プライバシー</a>'
 'のページに書いています。</p>'}
<p>集めた配信のデータ（タイトル・チャンネル名など）は、YouTubeの規約に従って
30日を過ぎたら消しています。古い日の記録ページに配信の一覧が出ないのは
そのためです。</p>
"""


def amazon_tagged(url, tag):
    """Amazonの商品URLにアソシエイトIDを付ける。既に付いていればそのまま。"""
    if not url or not tag or "amazon.co.jp" not in url:
        return url
    return url if "tag=" in url else url + ("&" if "?" in url else "?") + "tag=" + quote_plus(tag)


def store_links(name, plat, cfg):
    """そのゲームを「実際に売っている店」へのリンクだけを作る。

    Amazonはランキング表には出さない（既定）。ゲーム名でキーワード検索を
    投げるしかなく、その結果が攻略本・フィギュア・パーカーだらけになる。
    Amazonは商品ページを特定するAPI（PA-API）を持っているが、それは
    「過去30日以内に発送済みの売上がある」ことが利用条件なので、
    アクセスが無い時期は使えない。当てにできる土台ではない。

    読者に間違ったリンクを見せる損のほうが、2%の紹介料より大きい。
    出すのは、人が実際に商品ページを確かめたコラムの中だけにする。
    """
    # plat が None なら「機種が分からない」なので、どちらの店も出す。
    # 空のリスト [] は「PCでもゲーム機でも売っていない」（スマホ専用など）。
    on_pc = plat is None or "pc" in plat
    on_console = plat is None or "console" in plat

    steam = ("https://store.steampowered.com/search/?term=" + quote(name)) if on_pc else None
    amazon = None
    tag = (cfg.get("amazon_tag") or "").strip()
    if tag and on_console and cfg.get("amazon_in_ranking"):
        amazon = ("https://www.amazon.co.jp/s?k=" + quote_plus(name)
                  + "&tag=" + quote_plus(tag))
    return steam, amazon


def hot_facts(rising, gdays):
    """急上昇に入った各ゲームの「書くときに要る事実」を集める。

    なぜ要るか（2026-09-26 たろちんさん）:
      「『このゲームがアツい！』はサムネとタイトルと件数が並んでいるだけ。
        ここに3行サマリーみたいなものを足すのは意味がある」

    その3行を書くのは朝の定期実行（人の目が入る側）だが、**書く材料が
    手元に無いと、書けるのは数字の言い換えだけになる。**
    「2年以上前のゲームが上がっている」「同じ日に懐かしいRPGが2本並んだ」
    のような一文は、発売年とジャンルと過去の登場日が分かって初めて書ける。
    だからここで、判断に要る事実だけを leads.json に書き出しておく。

    **ここでは文章を作らない。** 事実だけ渡して、何を書くかは人に任せる。
    機械に「懐かしRPGが人気」と言わせると、当たっている日はよいが、
    外した日にサイトが嘘をつくことになる。
    """
    cat = {}
    for g in M.catalogue():
        cat.setdefault(g["name"], g)
    out = []
    for r in rising or []:
        # カタログは正式名で引く。日ごとの記録（game_days.json）は
        # **画面に出している表記**で保存されているので、そちらは r["game"]。
        # ここを取り違えると、前にも出ているゲームが毎日「初登場」になる。
        meta = cat.get(r.get("canonical") or r["game"]) or {}
        prev = sorted(d for d, games in (gdays or {}).items()
                      if r["game"] in games and d < today())
        out.append({
            "game": r["game"],
            "growth": r.get("growth"), "videos": r["videos"],
            "base": r.get("base"),
            "channels": r["channels"], "views": r["views"],
            # 誰が配信したか。1行に固有名詞が1つあるだけで読み物になる
            "who": [s["c"] for s in (r.get("streams") or [])][:5],
            "titles": [s["t"] for s in (r.get("streams") or [])][:3],
            "genres": meta.get("g") or [],
            # IGDBの発売年。辞書を作り直したあとから入る（古い辞書には無い）
            "year": meta.get("y"),
            "platforms": meta.get("p") or [],
            # 当サイトの記録。何日出たか・前はいつか・今日が初めてか
            "days_seen": len(prev),
            "last_seen": prev[-1] if prev else None,
            "first_here": not prev,
        })
    return out


def pick_rising(rows, momentum_ready):
    """急上昇に出す行を選ぶ。今日のページでも過去の記録ページでも同じ基準を使う。

    倍率の大きい順。小さくて誰も知らないゲームが上に来るようにする
    （2026-09-19 たろちんさん）。品質は本数ではなく「何人が別々に始めたか」で取る。
    """
    if not momentum_ready:
        return []
    return sorted(
        [r for r in rows
         if r["videos"] >= MIN_FOR_MOMENTUM
         and r["channels"] >= RISING_MIN_CHANNELS
         and (r["growth"] or 0) > 1.25],
        key=lambda r: -r["growth"])[:RISING_N]


ARCH_HOT_N = 3        # これまでの記録の一覧に、その日の急上昇を何本並べるか


def arch_hot(rising):
    """これまでの記録の一覧に出す、その日の急上昇。名前と倍率だけ。"""
    return [{"game": r["game"], "growth": r.get("growth"),
             "channels": r["channels"]} for r in (rising or [])[:ARCH_HOT_N]]


def compute_rows(videos, idx, disp, override, hist, day_names, momentum_ready,
                 plats=None, cfg=None):
    """その日の動画リストから、ランキングの行を作る。"""
    plats, cfg = plats or {}, cfg or {}
    games, unknown = tally(videos, idx, per_channel(cfg))
    rows = []
    for name, e in games.items():
        # n は連投を割り引いた件数（小数になる）。順位はこちらで決め、
        # 画面には四捨五入した整数を出す。raw は割引前の実数で、参考用。
        rows.append({"game": choose_name(name, disp.get(name), e["titles"], override),
                     "canonical": name, "videos": round(e["n"]), "n": round(e["n"], 1),
                     "raw": e["raw"],
                     "channels": len(e["channels"]), "views": e["views"],
                     "streams": sorted(e["streams"], key=lambda s: -s["v"])[:8],
                     "orgs": dict(sorted(e["orgs"].items(), key=lambda x: -x[1])),
                     "spark": [hist[d].get(name, 0) if d in hist else None
                               for d in day_names]})
    if rows:
        mx_v = max(r["n"] for r in rows) or 1
        mx_c = max(r["channels"] for r in rows) or 1
        logs_ = [math.log10(1 + r["views"]) for r in rows]
        lo, hi = min(logs_), max(logs_)
        for r in rows:
            r["p_videos"] = round(r["n"] / mx_v * 100)
            r["p_channels"] = round(r["channels"] / mx_c * 100)
            r["p_views"] = round((math.log10(1 + r["views"]) - lo) / max(1e-9, hi - lo) * 100)
            r["score"] = round(r["p_videos"] * W["videos"] + r["p_channels"] * W["channels"]
                               + r["p_views"] * W["views"], 1)
            # 急上昇は「実データのある過去の日」とだけ比べる
            past = [v for d, v in zip(day_names, r["spark"])
                    if d in hist and d != day_names[-1] and v is not None]
            if momentum_ready and past:
                # 「ふだん何件だったか」も持たせる。倍率だけだと、1件が3件に
                # なっただけでも ×3 と出てしまい、読む側が大きさを測れない。
                r["base"] = round(sum(past) / len(past), 1)
                r["growth"] = round(r["videos"] / max(0.8, r["base"]), 2)
            else:
                r["growth"] = r["base"] = None
            r["steam"], r["amazon"] = store_links(
                r["game"], plats.get(r["canonical"]), cfg)
        rows.sort(key=lambda r: -r["score"])
        for i, r in enumerate(rows, 1):
            r["rank"] = i
    return rows, unknown


def main():
    idx = M.build_index()
    disp = M.load_display()
    plats = M.load_platforms()
    cfg = read_json(DATA / "site_config.json", {}) or {}
    override = read_json(DATA / "display_names.json", {}) or {}
    if not cfg.get("amazon_tag"):
        log("AmazonアソシエイトIDが未設定です（data/site_config.json）。"
            "Amazonのリンクは出しません。")
    if not plats:
        log("対応機種の情報がありません。ワークフロー2をゲーム辞書ありで動かすと、"
            "PC専用ゲームにAmazonリンクを出さないようになります。")
    all_videos, runs = load_all()
    days = windows(all_videos, runs)
    day_names = [d for d, _, _ in days]
    have = [d for d, _, ok in days if ok]
    today_videos = days[-1][1]
    log(f"収集ファイル {len(runs)} 個 / 重複を除いた動画 {len(all_videos)} 本")
    log("直近7×24時間: " + " ".join(f"{d}={len(v) if ok else '-'}"
                                    for d, v, ok in days))
    log(f"データのある区間: {len(have)} / 急上昇の表示には {MIN_HISTORY} 区間必要")

    # 区間ごとのゲーム別本数（推移と急上昇に使う）
    hist = {}
    for day, vids, ok in days:
        if not ok:
            continue
        g, _ = tally(vids, idx, per_channel(cfg))
        hist[day] = {k: round(v["n"], 1) for k, v in g.items()}
    momentum_ready = len(have) >= MIN_HISTORY

    rows, unknown = compute_rows(today_videos, idx, disp, override,
                                 hist, day_names, momentum_ready, plats, cfg)
    if not rows:
        log("今日のデータからゲームを検出できませんでした。処理を続けます。")

    # 急上昇は「倍率の大きい順」。小さくて誰も知らないゲームが出るようにする。
    #
    # このサイトを作ったきっかけが「まだ誰も配信していないゲームを掘り出したい」
    # なので、ここは大きいゲームに譲らない（2026-09-19 たろちんさん）。
    # 倍率順なら自然と小さいものが上に来る。大きいゲームは、よほどの企画が
    # 立ったときだけ高い倍率になって入ってくる。特別扱いはしない。
    #
    # 品質の担保は本数ではなく「何人が別々に始めたか」で取る。
    # 1〜2人だと、ひとりの思いつきや連番の区切り方のブレが混ざる。
    # 3人が同じ日に別々に触っているなら、それは見つけてよい兆しである。
    # 26日ぶんで数えたところ、3人以上の候補は1日あたり37件あり、6件出しても
    # 毎日3.5件が入れ替わる（22日間で68種類、件数の中央値4.5件）。
    rising = pick_rising(rows, momentum_ready)
    # 急上昇が出せない間は「今日いちばん多くの配信者が触ったゲーム」を代わりに出す
    spread = sorted(rows, key=lambda r: (-r["channels"], -r["videos"]))[:3]

    # 検証を通らないコラムは載せない。無理に載せるより、無いほうがいい。
    #
    # ただし「今日の分がまだ無い」あいだ、コラム欄ごと消えてしまうのは避ける。
    # ここはサイトの顔なので、常に何か載っているほうがいい。
    # 今日の分が用意できるまでは、直近に書いたものをそのまま出す。
    # そのかわり見出しに日付を入れて、いつ書いたものかを必ず示す
    # （今日のことのように見せない）。
    column, column_day = None, today()
    for back in range(0, COLUMN_FALLBACK_DAYS + 1):
        day = (datetime.now(JST) - timedelta(days=back)).strftime("%Y-%m-%d")
        # 今日の分だけは、落ちた理由をログに出す。過去の分は静かに探す。
        c = load_valid(DATA / "columns" / f"{day}.json",
                       log if back == 0 else (lambda *a, **k: None))
        if c:
            column, column_day = c, day
            if back:
                log(f"今日のコラムがないため、{day} のコラムを表示します")
            break
    if column and column.get("buy"):
        column["buy"] = dict(column["buy"],
                             u=amazon_tagged(column["buy"].get("u", ""),
                                             (cfg.get("amazon_tag") or "").strip()))
    if column:
        enrich_column(column, rows)

    if column:
        column["date"] = column_day

    # 週・月のまとめ。トップにも1本出すので、payload を作る前に読んでおく。
    specials = load_specials()
    matome = latest_special(specials)

    payload = {
        "mode": "day",
        "date": today(),
        "column": column,
        "matome": matome,
        "generated": datetime.now(JST).strftime("%Y-%m-%d %H:%M"),
        "range": "直近24時間",
        "days": list(day_names),
        "totals": {"videos": len(today_videos), "games": len(rows),
                   "channels": len({v["channel_id"] for v in today_videos})},
        "rising": rising,
        "spread": spread,
        "momentum": {"ready": momentum_ready, "days": len(have), "need": MIN_HISTORY},
        "ranking": rows[:30],
        # 判定できなかったタイトルは公開ページには出さない。
        # ランキングに混ぜない方針は変えず、辞書を育てるための材料として
        # site/admin/ 側にだけ置く。
    }
    write_json(SITE / "data.json", payload)

    import json
    tpl = (SITE / "template.html").read_text(encoding="utf-8")

    # XやDiscordにURLを貼ったときのカード（OGP）は、相対パスでは出ない。
    # 画像もページのURLも「https://…」から書く必要があるので、
    # サイトの住所を data/site_config.json から持ってくる。
    site_url = (cfg.get("site_url") or "").strip().rstrip("/")

    def render(path, data, depth):
        render_page(path, data, depth, site_url)

    render("index.html", payload, 0)
    # その日の記録を、消えない住所に残す
    render(f"d/{today()}/index.html", dict(payload, view="archive"), 2)

    # ---- 管理用ページ（トップからはリンクしない） ----
    # よく出るタイトルを data/aliases.json に足していくための作業台。
    # 未判定のタイトルは「【】に書かれていたゲーム名」でまとめる。
    #
    # 以前は1本ずつ並べ、同じ題名が何本あったかで並べていた。だが新作は
    # 配信者ごとに題名が違うので、8人が配信していても n=1 の行が8つに散り、
    # 200件の中に埋もれていた。2026-09-20に『デスゲームの報告書』が
    # 19日間ずっと見落とされていたのが分かったのは、これが原因だった
    # （最大で1日8チャンネル、のべ17チャンネルが配信していた）。
    #
    # 何人が配信したかで並べれば、新作ほど上に来る。辞書に足すべきものが
    # 一番上に出る、という当たり前の形にする。
    groups = defaultdict(lambda: {"name": "", "chs": set(), "n": 0, "ex": []})
    for u in unknown:
        key = M.compact(u.get("guess") or u["title"])[:24]
        g = groups[key]
        g["name"] = g["name"] or (u.get("guess") or u["title"])
        g["chs"].add(u.get("channel") or "")
        g["n"] += 1
        if len(g["ex"]) < 3:
            g["ex"].append({"t": u["title"], "c": u.get("channel") or "", "u": u["u"]})
    unk_rows = [{"guess": g["name"], "channels": len(g["chs"]), "n": g["n"],
                 "examples": g["ex"]} for g in groups.values()]
    unk_rows.sort(key=lambda u: (-u["channels"], -u["n"]))
    for u in unk_rows:
        if u["channels"] >= UNKNOWN_ALERT:
            log(f"辞書に無いかもしれません: 「{u['guess']}」を "
                f"{u['channels']}チャンネルが配信しています（{u['n']}本）。"
                "ゲームなら data/aliases.json に足してください")
    leads = find_leads(today_videos, rows, hist, day_names)
    drift = find_drift(today_videos, idx)
    _, tagnotes = tag_games(today_videos, idx)
    # 見落とし候補。1日だけだと2人ずつに散って埋もれるので、直近7日をまとめて数える。
    # 『デスゲームの報告書』が19日間気付かれなかったのは、1日ぶんだけ見ていたため。
    miss_win = {}
    for _d, _vs, _ok in days[-MISS_DAYS:]:
        for _v in _vs:
            miss_win[_v["id"]] = _v
    misses = find_misses(list(miss_win.values()), idx,
                         tag_games(list(miss_win.values()), idx)[0])
    for m in misses:
        if m["kind"] == "near":
            log(f"辞書に無いかもしれません（候補あり）: 「{m['word']}」"
                f"{m['channels']}ch／{m['n']}本 → カタログの"
                f"「{m['suggest'][0]}」かもしれません（data/aliases.json）")
        else:
            log(f"辞書に無いかもしれません（{MISS_DAYS}日で{m['channels']}ch）: "
                f"「{m['word']}」{m['n']}本。ゲームなら data/aliases.json に、"
                "配信のラベルや事務所名なら data/miss_blocklist.json に足してください")
    for t in tagnotes:
        log(f"企画タグ #{t['tag']} から {t['added']} 本を「{t['game']}」として数えました"
            f"（{t['channels']}人が使用、うち{t['evidence']}本にゲーム名の記載あり）")
    for d in drift:
        log(f"辞書に足りない続編かもしれません: 「{d['written']}」を"
            f"{d['channels']}人が書いていますが、"
            f"「{d['game']}」として数えています（data/aliases.json）")
    recent_cols = []
    for f in sorted((DATA / "columns").glob("*.json"))[-14:]:
        c = read_json(f, None) or {}
        if c.get("game"):
            recent_cols.append({"date": f.stem, "game": c["game"],
                                "headline": c.get("headline", "")})
    admin = {"mode": "admin", "date": today(),
             "generated": payload["generated"], "unknown": unk_rows,
             "leads": leads, "drift": drift, "tags": tagnotes,
             "misses": misses, "miss_days": MISS_DAYS,
             # robots.txt で検索避けしてあるが、題まで同じにしておく理由はない
             "meta_title": "管理用 ｜ ハヤリゲー",
             "meta_og": "管理用",
             "meta_desc": "判定できなかった配信と、コラムの種。公開ページではありません。",
             "recent_columns": recent_cols[::-1]}
    render("admin/index.html", admin, 1)
    write_json(SITE / "admin" / "unknown.json", admin)
    # robots.txt で /admin/ を検索避けしているが、それだと外から読む手段まで
    # 塞がってしまう。中身は公開データの集計でしかないので、機械で読む用は
    # 直下にも置く（トップからはリンクしない）。
    # 「今日の見どころ」を書くための材料。文章はここでは作らない（hot_facts の説明）
    hfacts = hot_facts(rising, read_json(DATA / "game_days.json", {}) or {})
    write_json(SITE / "leads.json",
               {"date": today(), "generated": payload["generated"],
                "leads": leads, "drift": drift, "tags": tagnotes,
                "misses": misses, "miss_days": MISS_DAYS,
                "hot_facts": hfacts,
                "notes_written": bool((column or {}).get("notes")),
                "recent_columns": recent_cols[::-1]})

    # ---- アーカイブ一覧を更新する ----
    idx_path = DATA / "archive_index.json"
    entries = {e["date"]: e for e in (read_json(idx_path, []) or [])}
    entries[today()] = {
        "date": today(),
        "videos": payload["totals"]["videos"],
        "channels": payload["totals"]["channels"],
        "games": payload["totals"]["games"],
        "hot": arch_hot(rising),
        "top": [{"game": r["game"], "videos": r["videos"], "channels": r["channels"]}
                for r in rows[:5]],
        "column": {"game": column["game"], "headline": column["headline"]} if column else None,
    }
    # アーカイブの仕組みを入れる前に集めた日を、あとから記録に足す。
    # 更新が1日こけたときの穴埋めにもなる。
    # 直近1週間は毎回作り直す（デザインを直したときに反映されるように）。
    # それより古い日は、ページが無いときだけ作る。毎日全部作り直すと、
    # 記録がたまるほど処理時間が伸びてしまうため。
    buckets = by_calendar_day(all_videos)
    # 辞書を直した日は、手元に残っている日ぶん全部を作り直す。
    #
    # 2026-09-20に「デスゲームの報告書」「トルネコの大冒険」など14タイトルを
    # 足したとき、その日から先は直るのに、過去の記録ページは古い判定のまま
    # 残ることに気づいた。同じ日の同じ配信なのに、ページによって数字が違う
    # のはおかしい。辞書を直したら過去にも反映する、を既定の動きにする。
    #
    # 作り直せるのは data/daily に元データが残っている30日ぶんだけ。
    # それより前は元データを消してある（YouTubeの規約）ので直せない。
    # だから、辞書に足すのは早いほうがよい。
    gdays = read_json(DATA / "game_days.json", {}) or {}
    state = read_json(DATA / "build_state.json", {}) or {}
    fingerprint = matcher_fingerprint()
    remake_all = state.get("fingerprint") != fingerprint
    # 記録（game_days.json）が無い日は、元データが残っているうちに作り直す。
    # 日別ファイルは30日で消えるので、取りこぼすと二度と作れない。
    missing = [d for d in sorted(buckets) if d not in gdays]
    recent = sorted(buckets) if remake_all else sorted(
        set(sorted(buckets)[-7:]) | set(missing))
    if missing and not remake_all:
        log(f"ゲームの記録が無い日が {len(missing)} 日ありました。"
            f"元データが残っているうちに作り直します")
    if remake_all:
        log(f"辞書まわりに変更がありました。手元に残っている "
            f"{len(buckets)} 日分の記録ページを作り直します")
    # 収集を始める前の日は「その日の記録」として不完全なので載せない。
    # 収集は48時間ぶんを取るが、控えめに1日ぶんだけ信用する。
    cover_from = ((datetime.strptime(runs[0], "%Y-%m-%d") - timedelta(days=1))
                  .strftime("%Y-%m-%d") if runs else "9999-12-31")

    # 記録のページにも「アツい！」（急上昇）を残す（2026-09-26 たろちんさん）
    #
    #   「このサイトの核は『次に流行るゲーム』で、それはランキングよりも
    #     毎日のコラムと急上昇の観測なのだから」
    #
    # これまで、過去の日のページは rising を空にして作り直していた。
    # そのため辞書を直すたびに全ページが作り直され、**その日いちばん大事だった
    # 情報だけが毎回消えていた。** 代わりに「いちばん広がったゲーム」（配信者数順）
    # が出ていたが、それは順位表の言い換えでしかなく、兆しの記録にならない。
    #
    # 倍率は「その日の件数 ÷ 直前6日の平均」なので、手元に日別データが残って
    # いれば後から同じ数字を出せる。前の日の集計は使い回す（下の cal_hist）。
    cal_cache = {}

    def cal_hist(d):
        """その日のゲーム別本数。何度も呼ばれるので覚えておく。"""
        if d not in cal_cache:
            g, _ = tally(buckets.get(d, []), idx, per_channel(cfg))
            cal_cache[d] = {k: round(v["n"], 1) for k, v in g.items()}
        return cal_cache[d]

    def past_window(d):
        """(その日までの7日, 実データのある日の集計) を返す。"""
        base = datetime.strptime(d, "%Y-%m-%d")
        names = [(base - timedelta(days=k)).strftime("%Y-%m-%d")
                 for k in range(DAYS - 1, -1, -1)]
        return names, {n: cal_hist(n) for n in names if buckets.get(n)}

    added = 0
    for day in sorted(buckets):
        if day == today() or day < cover_from:
            continue
        fresh = day in recent or not (SITE / "d" / day / "index.html").exists()
        if day in entries and not fresh:
            continue
        vids = buckets[day]
        if not vids:
            continue
        # 今日のページと同じ形で倍率を出す。日別データが足りない古い日は
        # momentum_ready が False になり、これまでどおり「広がり」を出す。
        win, whist = past_window(day)
        ready = len(whist) >= MIN_HISTORY
        past_rows, _ = compute_rows(vids, idx, disp, override, whist, win, ready,
                                    plats, cfg)
        if not past_rows:
            continue
        past_rising = pick_rising(past_rows, ready)
        col = read_json(DATA / "columns" / f"{day}.json", None)
        # 記録のページでも、今日のページと同じようにサムネイルを出す
        enrich_column(col, past_rows)
        entries[day] = {
            "date": day, "videos": len(vids), "games": len(past_rows),
            "channels": len({v["channel_id"] for v in vids}),
            "hot": arch_hot(past_rising),
            "top": [{"game": r["game"], "videos": r["videos"], "channels": r["channels"]}
                    for r in past_rows[:5]],
            "column": {"game": col["game"], "headline": col["headline"]} if col else None,
        }
        render(f"d/{day}/index.html",
               {"mode": "day", "view": "archive", "date": day, "column": col,
                "generated": "", "days": [], "rising": past_rising,
                "spread": past_rows[:3],
                "momentum": {"ready": ready, "days": len(whist),
                             "need": MIN_HISTORY},
                "totals": {"videos": entries[day]["videos"], "games": len(past_rows),
                           "channels": entries[day]["channels"]},
                "ranking": past_rows[:30]}, 2)
        gdays[day] = day_games(past_rows)
        added += 1
    if added:
        log(f"過去 {added} 日分のページを作り直しました")
    # 今日ぶんの全ゲームを記録に残す。日別ファイルは30日で消えるので、
    # ここで残しておかないと、あとから数え直せない。
    gdays[today()] = day_games(rows)
    keep_days = {d.name for d in (SITE / "d").iterdir() if d.is_dir()} \
        if (SITE / "d").is_dir() else set(gdays)
    gdays = {k: v for k, v in gdays.items() if k in keep_days or k >= min(keep_days or {k})}
    write_json(DATA / "game_days.json", dict(sorted(gdays.items())))
    log(f"ゲームの日ごとの記録: {len(gdays)} 日分 "
        f"／ 今日は {len(gdays[today()])} 種（2チャンネル以上）")
    write_json(DATA / "build_state.json",
               {"_説明": "辞書まわりのファイルが変わったかどうかを見るための印です。"
                         "変わっていれば、過去の記録ページも作り直します。"
                         "中身に意味はないので、消しても次回また作られます。",
                "fingerprint": fingerprint, "updated": today()})

    archive = sorted(entries.values(), key=lambda e: e["date"], reverse=True)
    write_json(idx_path, archive)
    render("archive/index.html",
           {"mode": "archive", "date": today(), "archive": archive}, 1)

    # ---- 週・月のまとめ --------------------------------------------------
    # 読みものがこのサイトの本体なので、Xに流して消えるのはもったいない。
    for x in specials:
        _t = str((x.get("col") or {}).get("title") or x["heading"])
        _l = str((x.get("col") or {}).get("lead") or "")
        render(f'{x["slug"]}/{x["key"]}/index.html',
               {"mode": "page", "date": today(), "subtitle": x["heading"],
                "generated": payload["generated"],
                "meta_title": f'{_t} ｜ {x["heading"]} ｜ ハヤリゲー',
                "meta_og": _t,
                "meta_desc": _l or f'{x["heading"]}のまとめ。'
                                   "VTuber・ゲーム実況者のYouTube配信から。",
                "page_body": special_html(x)}, 2)
    render("matome/index.html",
           {"mode": "page", "date": today(), "subtitle": "週・月のまとめ",
            "generated": payload["generated"],
            "meta_title": "週・月のまとめ ｜ ハヤリゲー",
            "meta_og": "週・月のまとめ",
            "meta_desc": "1日を見ているだけでは分からないことを書いた読みもの。"
                         "その週・その月に配信界隈で何が起きたか。",
            "page_body": specials_index_html(specials)}, 1)
    if specials:
        log(f"週・月のまとめを {len(specials)} 本書き出しました")

    # ---- 説明ページ ----------------------------------------------------
    # 数字を出すサイトなので、どう数えているかが読めることが信用に直結する。
    # 「Shortsと切り抜きは除く」「連番は1件」などは、書いていなければ
    # 誰にも伝わらない。
    render("privacy/index.html",
           {"mode": "page", "date": today(), "subtitle": "お問い合わせ・プライバシー",
            "generated": payload["generated"],
            "meta_title": "お問い合わせ・プライバシー ｜ ハヤリゲー",
            "meta_og": "お問い合わせ・プライバシー",
            "meta_desc": "連絡先と、アクセス解析・外部リンク・集めているデータの扱いについて。",
            "page_body": privacy_html(cfg)}, 1)

    render("about/index.html",
           {"mode": "page", "date": today(), "subtitle": "このサイトについて",
            "generated": payload["generated"],
            "meta_title": "このサイトについて ｜ ハヤリゲー",
            "meta_og": "ハヤリゲーの作り方",
            "meta_desc": "どのチャンネルを、どう数えて、どう順位を付けているか。"
                         "集計の範囲と、数に入れていないものについて書いています。",
            "page_body": about_html(cfg, watched_channels())}, 1)

    # ---- ゲームを探す ----------------------------------------------------
    # 「このゲーム、前はいつ入ってた？」に答える。記録が増えるほど価値が出る。
    search_index()
    render("search/index.html",
           {"mode": "page", "date": today(), "subtitle": "ゲームを探す",
            "generated": payload["generated"],
            "meta_title": "ゲームを探す ｜ ハヤリゲー",
            "meta_og": "ゲームを探す",
            "meta_desc": "ゲーム名を入れると、そのゲームがいつランキングに入っていたか、"
                         "コラムで取り上げた日があるかが分かります。",
            "page_body": search_html("../")}, 1)

    # ---- /d/ と /w/ の入口 ----------------------------------------------
    # 記録は /d/2026-09-24/ に、まとめは /w/2026-09-14/ に置いてあるが、
    # 親の /d/ と /w/ には何も無かった。人がURLを削って試すこともあるし、
    # 検索エンジンは親の階層をたどりに来る。そこが404を返していた。
    # 中身のある一覧（/archive/ と /matome/）へ送る。
    # 検索結果には出さない（そこに出すべきは送り先のほうなので）。
    for src, dst, name in (("d", "archive", "日ごとの記録"),
                           ("w", "matome", "週・月のまとめ")):
        to = f"{site_url}/{dst}/" if site_url else f"/{dst}/"
        d = SITE / src
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.html").write_text(
            f'<!doctype html><html lang="ja"><head><meta charset="utf-8">'
            f'<meta name="robots" content="noindex">'
            f'<link rel="canonical" href="{to}">'
            f'<meta http-equiv="refresh" content="0; url={to}">'
            f'<title>{name}｜ハヤリゲー</title></head>'
            f'<body><p><a href="{to}">{name}の一覧へ</a></p></body></html>\n',
            encoding="utf-8")

    # ---- sitemap.xml ---------------------------------------------------
    # 日付ごとの記録は日が経つほど増える資産だが、たどり着く道が
    # トップからのリンクしかない。存在をまとめて知らせる。
    if site_url:
        urls = [(f"{site_url}/", "daily", "1.0"),
                (f"{site_url}/about/", "monthly", "0.5"),
                (f"{site_url}/privacy/", "yearly", "0.3"),
                (f"{site_url}/archive/", "daily", "0.6"),
                (f"{site_url}/search/", "weekly", "0.6"),
                (f"{site_url}/matome/", "weekly", "0.8")]
        urls += [(f"{site_url}/{x['slug']}/{x['key']}/", "monthly", "0.7")
                 for x in specials]
        urls += [(f"{site_url}/d/{a['date']}/", "monthly", "0.4") for a in archive]
        body = "".join(
            f"<url><loc>{u}</loc><changefreq>{f}</changefreq><priority>{pr}</priority></url>"
            for u, f, pr in urls)
        (SITE / "sitemap.xml").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            + body + "</urlset>", encoding="utf-8")
        # robots.txt の Sitemap 行は、毎回いまの住所で書き直す。
        # 「無いときだけ足す」にしていたため、独自ドメインに移したあとも
        # 古いURLが残っていた（2026-09-21に気づいた）。
        rb = SITE / "robots.txt"
        txt = rb.read_text(encoding="utf-8") if rb.exists() else "User-agent: *\nAllow: /\n"
        keep = [ln for ln in txt.splitlines() if not ln.startswith("Sitemap:")]
        # tweet.txt はXに貼る文の置き場。読み物ではないので検索には出さない。
        if not any(ln.strip() == "Disallow: /tweet.txt" for ln in keep):
            for i, ln in enumerate(keep):
                if ln.startswith("Disallow: /admin/"):
                    keep.insert(i + 1, "Disallow: /tweet.txt")
                    break
            else:
                keep.append("Disallow: /tweet.txt")
        rb.write_text("\n".join(keep).rstrip()
                      + f"\n\nSitemap: {site_url}/sitemap.xml\n", encoding="utf-8")
        log(f"sitemap.xml を書き出しました（{len(urls)} ページ）")

    # ---- ads.txt（AdSenseのサイトIDを入れたときだけ出す） ----
    at, atp = ads_txt(cfg), SITE / "ads.txt"
    if at:
        if not atp.exists() or atp.read_text(encoding="utf-8") != at:
            atp.write_text(at, encoding="utf-8")
            log("ads.txt を書き出しました（AdSenseの広告枠の持ち主を宣言するファイル）")
    elif atp.exists():
        atp.unlink()
        log("ads.txt を消しました（site_config.json の adsense_pub_id が空です）")
    if ads_mode(cfg) == ADS_ON and not at:
        log("広告を『掲載中』にしていますが、adsense_pub_id が空なので "
            "ads.txt が出ません（data/site_config.json）")

    # YouTubeの規約で、配信タイトルなどを持てるのは30日まで
    purge_old(site_url)

    log(f"サイトを書き出しました: {len(rows)} タイトル / 急上昇 {len(rising)} 件 "
        f"/ 確認待ち {len(unknown)} 件 / 見落とし候補 {len(misses)} 件")
    log(f"アーカイブ: {len(archive)} 日分（site/d/{today()}/ に本日分を保存）")


if __name__ == "__main__":
    main()
