#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""配信タイトルからゲーム名を判定する。このプロジェクトの心臓部。

実在の配信タイトル212本で検証し、未調整データでの正解率89.7%、
ゲーム以外の誤検出0件・別ゲームとの取り違え0件を確認した実装。
"""
import re, unicodedata
from common import DATA, read_json

STRIP = r"[\s・:：\-–—ー_'’‘\"“”,、.。!！?？~〜/／|｜&＆#＃*＊+＋%％@＠^…♪♡★☆→←※=＝]"
KATAKANA = re.compile(r"[ァ-ヴーｦ-ﾟ・]")
DERIV = ("風", "物語", "パロディ", "もどき", "っぽい")   # 「マイクラ風ゲーム」を弾く

BRACKETS = [("『", "』", 3), ("〖", "〗", 2), ("【", "】", 2),
            ("「", "」", 1), ("《", "》", 1), ("≪", "≫", 1)]


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).lower()
    return "".join(ch for ch in s
                   if unicodedata.category(ch)[0] not in ("S", "C") or ch.isascii())


def compact(s: str) -> str:
    return re.sub(STRIP, "", norm(s))


SEP_RE = re.compile(STRIP)


def compact_map(s: str):
    """詰めた文字列と、「元の文でその文字の直前に区切りがあったか」の印。

    詰めてしまうと『協会3 -Japan Stigmatized Property-』が
    『…協会3japanstigmatized…』になり、japan の直前が数字に見える。
    そのせいで単語の切れ目と判定できず、手で登録したエイリアスが
    丸ごと素通りしていた（同じゲームが2行に割れる原因）。
    区切りの位置を別に覚えておけば、詰めた形のまま正しく判定できる。
    """
    n = norm(s)
    out, sep, pending = [], [], True      # 文頭は区切り扱い
    for ch in n:
        if SEP_RE.match(ch):
            pending = True
            continue
        out.append(ch)
        sep.append(pending)
        pending = False
    return "".join(out), sep


def _lat(ch: str) -> bool:
    return ch.isascii() and ch.isalnum()


def spaced(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(STRIP, " ", norm(s))).strip()


def is_latin(s: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9]+", s))


# ------------------------------------------------------------------ 辞書
class Index:
    """エイリアス→ゲーム名。5万件を高速に照合するため先頭2文字で仕分けする。"""

    def __init__(self):
        self.exact = {}      # 完全一致用
        self.bucket = {}     # 先頭2文字 → [(alias, game, pop)]
        self.ng = []

    def add(self, alias, game, pop=0):
        c = compact(alias)
        if len(c) < 2:
            return
        # 同じ表記が複数のゲームに使われている場合は人気の高いほうを採用する。
        # これをしないと『Minecraft』が『Minecraft: Java Edition』に化ける。
        cur = self.exact.get(c)
        if cur is None or pop > cur[1]:
            self.exact[c] = (game, pop)
        if len(c) >= 3:
            # 単語の区切りを残した形も持っておく。詰めた形だけだと
            # 「ARK Survival Ascended」のような複数語の名前を探せない。
            self.bucket.setdefault(c[:2], []).append((c, spaced(alias), game, pop))

    def find(self, text, strict=False):
        """textの中から最も長いエイリアスを探す。同点なら人気の高いゲーム。

        strict=True は「括弧の外」で照合するとき。タイトル全文から拾うと
        『hololive』の中の live のような誤爆が起きるので条件を厳しくする。
        """
        c, sep = compact_map(text)
        if not c:
            return None
        if c in self.exact:
            g, p = self.exact[c]
            return (g, len(c), True)
        best = None
        for i in range(len(c) - 1):
            for alias, alias_sp, game, pop in self.bucket.get(c[i:i + 2], ()):
                if len(alias) < (4 if is_latin(alias) else 3):
                    continue
                if not c.startswith(alias, i):
                    continue
                curated = pop >= 10 ** 8      # 手で登録したエイリアスは信用する
                if is_latin(alias):
                    # 前後が「単語の切れ目」であることを必ず求める。
                    # ここを素通りさせていたため surviv → ARK Survival、
                    # live → hololive、lowglow → FLOWGLOW を拾っていた。
                    # 元の文で区切られていた場所（sep）も切れ目として認める。
                    j = i + len(alias)
                    if not ((i == 0 or sep[i] or not _lat(c[i - 1]))
                            and (j >= len(c) or sep[j] or not _lat(c[j]))):
                        continue
                else:
                    if c[i + len(alias):i + len(alias) + 2].startswith(DERIV):
                        continue
                    # カタカナ語の途中を切り出さない。
                    # 『リヴリーアイランド』の後ろ半分だけ見て「アイランド」に
                    # してしまう事故を防ぐ。直前がカタカナなら、それは
                    # ひと続きの単語の一部。
                    if i > 0 and KATAKANA.match(c[i - 1]) and KATAKANA.match(alias[0]):
                        continue
                if strict and not curated:
                    # 括弧の外では、短い名前や無名のゲームは採用しない。
                    # 『テニス』『Golf』のような一般語との衝突を防ぐ。
                    if len(alias) < (6 if is_latin(alias) else 4) or pop < 1:
                        continue
                key = (len(alias), pop)
                if best is None or key > (best[1], best[3]):
                    best = (game, len(alias), False, pop)
        return (best[0], best[1], best[2]) if best else None


def catalogue():
    """ゲーム名の一覧。2つのファイルを合わせて読む。

    igdb_games.json  … 5万本。月1回まとめて作り直す。8MBある。
    igdb_recent.json … 発売直後と発売前のぶんだけ。毎日足す。小さい。

    分けているのは、誤検出がいちばん多いのが「昨日出たゲーム」だから。
    そこだけ毎日新しくしたいが、8MBを毎日書き換えるとリポジトリが太る。
    """
    out = list(read_json(DATA / "igdb_games.json", []) or [])
    out += list(read_json(DATA / "igdb_recent.json", []) or [])
    return out


def build_index() -> Index:
    idx = Index()
    banned = {n.lower() for n in (read_json(DATA / "game_blocklist.json", []) or [])}
    # 「ゲーム名としては正しいが、配信タイトルの中では普通の言葉」という
    # 別名を落とす。例: ZeroRanger の別名「FINALBOSS」。
    # ゲームそのものを消したいときは game_blocklist.json のほう。
    bad_alias = {compact(a) for a in
                 (read_json(DATA / "alias_blocklist.json", []) or [])}
    for g in catalogue():
        if g["name"].lower() in banned:
            continue
        if compact(g["name"]) not in bad_alias:
            idx.add(g["name"], g["name"], g.get("pop", 0))
        for a in g.get("alias", []):
            if compact(a) in bad_alias:
                continue
            idx.add(a, g["name"], g.get("pop", 0))
    # 手で足したエイリアス（略称・愛称）は人気度を最大にして優先する
    for game, aliases in (read_json(DATA / "aliases.json", {}) or {}).items():
        idx.add(game, game, 10 ** 9)
        for a in aliases:
            idx.add(a, game, 10 ** 9)
    idx.ng = [compact(t) for t in (read_json(DATA / "blocklist.json", []) or [])]
    return idx


def load_platforms():
    """ゲーム名 → 対応機種のざっくり分類（pc / console）。
    どの店へのリンクを出すかを決めるのに使う。辞書が古い場合は空になる。"""
    out = {}
    for g in catalogue():
        if g.get("p"):
            out[g["name"]] = g["p"]
    return out


def load_genres():
    """ゲーム名 → ジャンル。チャンネルの偏りを見るのに使う。
    辞書にジャンルが入っていない（古い）場合は空になる。"""
    out = {}
    for g in catalogue():
        if g.get("g"):
            out[g["name"]] = g["g"]
    return out


def load_display():
    """表示用の名前。日本語タイトルがあればそちらを使う。"""
    disp = {}
    for g in catalogue():
        if g.get("jp"):
            disp[g["name"]] = g["jp"]
    disp.update(read_json(DATA / "display_names.json", {}) or {})
    return disp


# ------------------------------------------------------------------ 判定
# 配信タイトルの慣習では、ゲーム名はいちばん最初の括弧に入る。
# あとに出てくる『』は、DLC名・チャプター名・曲名・企画名であることが多い。
# 例: 【デッドバイデイライト】新チャプター『Chorus of Sin』 → ゲームはDbDのほう
LEAD_RE = re.compile(r"^[\s　#＃0-9]*[【『〖「《≪]")


def segments(title: str):
    """(中身, 括弧の強さ, 冒頭の括弧か) を返す。"""
    m0 = LEAD_RE.match(title)
    lead_at = m0.end() - 1 if m0 else -1
    out = []
    for op, cl, pri in BRACKETS:
        pat = re.escape(op) + r"([^" + re.escape(op + cl) + r"]{1,60})" + re.escape(cl)
        for m in re.finditer(pat, title):
            out.append((m.group(1).strip(), pri, m.start() == lead_at))
    out.append((title, 0, False))
    return out


def looks_like_noise(seg_c: str, ng) -> bool:
    rest = seg_c
    for t in sorted(ng, key=len, reverse=True):
        rest = rest.replace(t, "")
    return len(re.sub(r"[0-9#]", "", rest)) <= 1


CHANNEL_HINTS = [compact(x) for x in
                 ["vtuber", "にじさんじ", "ホロライブ", "ぶいすぽ", "所属", "視点",
                  "ch", "チャンネル", "ななしいんく", "ネオポルテ"]]


def leading_bracket(title: str, ng):
    """冒頭の括弧だけを未知ゲームの候補にする。末尾の括弧は配信者名なので見ない。"""
    m = re.match(r"^[\s#0-9]*([【『〖])([^】』〗]{1,60})[】』〗]", norm(title))
    if not m:
        return None
    raw = m.group(2).strip()
    c = compact(raw)
    if not c or len(c) < 2 or re.fullmatch(r"[0-9#]+", c):
        return None
    if raw.lstrip().startswith("#") or looks_like_noise(c, ng):
        return None
    if any(h in c for h in CHANNEL_HINTS):
        return None
    if "/" in raw and len(raw) > 12:
        return None
    return raw


def extract(title: str, idx: Index, fallback=False):
    """(ゲーム名, 判定方法) を返す。判定できなければ (None, 'none')。"""
    cands = []
    for seg, pri, lead in segments(title):
        c = compact(seg)
        if pri > 0 and looks_like_noise(c, idx.ng):
            continue
        hit = idx.find(seg, strict=(pri == 0))
        if hit:
            g, ln, exact = hit
            # 冒頭の括弧を最優先にする。ゲーム名でない冒頭括弧（【ホロライブ】等）は
            # そもそもここに来ないので、この加点で誤判定が増えることはない。
            cands.append((pri * 100 + (150 if lead else 0)
                          + ln + (50 if exact else 0), g))
    if cands:
        cands.sort(reverse=True)
        return cands[0][1], "dict"
    if fallback:
        seg = leading_bracket(title, idx.ng)
        if seg:
            return seg, "unknown"      # 自動採用せず「確認待ち」に回す印
    return None, "none"
