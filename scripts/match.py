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

# 小書きのカタカナと「ヵヶ」は、日本語の単語の先頭には立たない。
# だから、エイリアスの直後にこれが続いていたら、そこは単語の途中である。
# 2026-09-18に「モンストゥルム」を「モンスト」＝モンスターストライクとして
# 数えていたのを見つけて足した。「マイクラサバイバル」のように普通の
# カタカナが続くのは複合語として正しいので、そちらは弾かない。
SMALL_KANA = "ァィゥェォヵヶッャュョヮ"

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

    def add(self, alias, game, pop=0, exact_only=False):
        """エイリアスを1つ登録する。

        exact_only=True のときは**括弧の中身まるごと（または題名まるごと）が
        その字と一致したときだけ**当たるようにする。途中に含まれているだけでは
        当たらない（下の bucket に入れない）。

        なぜ要るか（2026-10-23 たろちんさんの報告）
        ------------------------------------------
        『あ。あ。あ。』という、声で操作するゲームが落ちていた。
        **compact() が「。」を落とすので、詰めると `あああ` になる。**
        これを普通の別名として足すと、

            「しゅばあああああああ」「きたああああ」「だあああ」

        のような題を全部さらってしまう。手元の記録で数えたら
        **`あああ` を含む題は138本・67チャンネル**あり、その100本は
        7 Days to Die・Apex・ドラゴンボールZカカロットなどに正しく
        入っている。足した瞬間にそれを全部奪う。

        かといって最低文字数を3→4に上げる手は使えない。3文字の非ラテン別名は
        262件あり、手で登録したものだけでも `ヴァロ` `デドバ` `スト6` `あつ森`
        `ウマ娘` `学マス` `パルワ` など24件が効いている。

        **「括弧まるごとのときだけ当てる」なら、どちらも壊さずに済む。**
        【あ。あ。あ。】は当たり、「しゅばあああ」は当たらない。
        2026-10-12に「条件付きで弾く仕掛けは、守るものが無いうちは作らない。
        ただし必要になる日は来る」と書いた、その日が来たということ。
        """
        c = compact(alias)
        if len(c) < 2:
            return
        # 同じ表記が複数のゲームに使われている場合は人気の高いほうを採用する。
        # これをしないと『Minecraft』が『Minecraft: Java Edition』に化ける。
        cur = self.exact.get(c)
        if cur is None or pop > cur[1]:
            self.exact[c] = (game, pop)
        if len(c) >= 3 and not exact_only:
            # 単語の区切りを残した形も持っておく。詰めた形だけだと
            # 「ARK Survival Ascended」のような複数語の名前を探せない。
            self.bucket.setdefault(c[:2], []).append((c, spaced(alias), game, pop))

    def find(self, text, strict=False, curated_only=False):
        """textの中から最も長いエイリアスを探す。同点なら人気の高いゲーム。

        strict=True は「括弧の外」で照合するとき。タイトル全文から拾うと
        『hololive』の中の live のような誤爆が起きるので条件を厳しくする。

        curated_only=True は「括弧の中を区切りで割ったぶん」で照合するとき
        （2026-11-05）。**手で登録した別名にしか当てない。**
        理由は `segments` の上のコメント（カタログ由来の短い名前を割って
        当てると、BW・PS2・ROM・PS・PE・WoW・TA が全部ゲーム名に化ける）。
        """
        c, sep = compact_map(text)
        if not c:
            return None
        if c in self.exact:
            g, p = self.exact[c]
            if not (curated_only and p < 10 ** 8):
                return (g, len(c), True)
            return None
        best = None
        for i in range(len(c) - 1):
            for alias, alias_sp, game, pop in self.bucket.get(c[i:i + 2], ()):
                if len(alias) < (4 if is_latin(alias) else 3):
                    continue
                if not c.startswith(alias, i):
                    continue
                curated = pop >= 10 ** 8      # 手で登録したエイリアスは信用する
                if curated_only and not curated:
                    continue
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
                    # 直後が小書きカタカナなら、単語の途中を切り出している。
                    nxt = c[i + len(alias):i + len(alias) + 1]
                    if nxt and nxt in SMALL_KANA:
                        continue
                    # 数字の途中で切らない。
                    # これが無いと「ファイナルファンタジーVII」の中の
                    # 「ファイナルファンタジーVI」が一致してしまい、FF7の配信が
                    # FF6として数えられる。ナンバリングの続編どうしで起きる。
                    # 見るのは数字とローマ数字だけにしてある。「龍が如く7｜Like a
                    # Dragon」「スト6DJ」のように、番号のすぐ後ろに別の語が
                    # くっつく書き方は珍しくないので、そこまで弾くと取りこぼす。
                    j = i + len(alias)
                    if j < len(c) and not sep[j]:
                        if (alias[-1].isdigit() and c[j].isdigit()) or \
                           (alias[-1] in "ivx" and c[j] in "ivx"):
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
                # 手で登録したエイリアスは、少しだけ長さを盛って優先する。
                # 「BIOHAZARD/バイオハザード6」のように英日を併記した題名だと、
                # 辞書由来の biohazard（9字）が、手で入れたバイオハザード6（8字）に
                # 長さで勝ってしまい、無印のバイオハザードに吸い込まれていた。
                score = len(alias) + (3 if curated else 0)
                key = (score, pop)
                if best is None or key > (best[1], best[3]):
                    best = (game, score, False, pop)
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


# リメイクの扱い（2026-09-08 たろちんさんと相談して決めた／2026-11-12に線を絞った）
#
#   ふだんはリメイクを数字の行にまとめる。分けない。
#   ただし新しいリメイクが出て配信が増え始めたら、そのタイトルだけ分ける。
#
# 理由: 分ける判定が正確にできるのは「配信者が商品名をそのまま書く時期」＝
# 発売直後だけ。実際に数えたところ、バイオハザード4は13本中6本にしか
# 「RE:4」の表記が無く、分けると勢いが2つの行に割れて両方とも順位が下がる。
# 単純な移植（コレクション収録など）は、いつでも同じ行のままでよい。
# 分けたくなったら、この下の aliases.json に1項目足すだけで済む。
#
# ★2026-11-12に足した線 ── この理由が効かない場合がある。
#
#   理由は「**同じ題で書かれるから分けられない**」。
#   題そのものが違うリメイクには、この理由が当てはまらない。
#
#     まとめる  バイオハザード4 / バイオハザード RE:4  … どちらとも書く
#     分ける    ポケットモンスター 赤 / ファイアレッド   … 「赤」と書く人は1人もいない
#
#   ポケモンのリメイクは判定が100%正確なので、分けても勢いは割れない。
#   逆にまとめると、ファイアレッドの配信が Pokémon Red Version として
#   表に出て、読者に別の商品名を見せてしまう。
#   2026-11-12に9行（ファイアレッド〜エメラルド）を手で立てた。
#   新しく152本・失った0本・移った0本。
#
# ※ カタログ（igdb_sync.py の where game_type = 0 & version_parent = null）は
#   リメイク・リマスター・移植・第3のバージョンを構造的に1行も取っていない。
#   だから手で立てたキーは、5万本を作り直しても重複しない。
#   くわしくは data/辞書の直し方.md の 2-10章。
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
    # 「まるごと一致のときだけ当てる」別名（2026-10-23）。
    # 詰めるとありふれた字になってしまう題名のためのもの。add() の説明を読むこと。
    only = {compact(a) for a in
            (read_json(DATA / "alias_exact_only.json", []) or [])}
    # 手で足したエイリアス（略称・愛称）は人気度を最大にして優先する
    for game, aliases in (read_json(DATA / "aliases.json", {}) or {}).items():
        idx.add(game, game, 10 ** 9, exact_only=compact(game) in only)
        for a in aliases:
            idx.add(a, game, 10 ** 9, exact_only=compact(a) in only)
    idx.ng = [compact(t) for t in (read_json(DATA / "blocklist.json", []) or [])]
    return idx


_PREFER = None


def prefer_long():
    """「この行が勝ったとき、同じ題にこちらも出ていればそちらを採る」組。

    data/長いほうを採る.json の `組` を {勝った行: 採りたい行} で読む。
    **両方が同じ題に出ているときしか効かない**ので、ここに書いた組以外は何も変わらない。
    """
    global _PREFER
    if _PREFER is None:
        _PREFER = dict((read_json(DATA / "長いほうを採る.json", {}) or {}).get("組") or {})
    return _PREFER


def load_platforms():
    """ゲーム名 → 対応機種のざっくり分類（pc / console）。
    どの店へのリンクを出すかを決めるのに使う。辞書が古い場合は空になる。

    手で足したゲーム（aliases.json のキー）は、IGDBの正式名と違う名前なので
    そのままでは機種が引けない。引けないと「どちらでも売っている」扱いになり、
    スプラトゥーン3やマリオカートに『Steamで探す』が出ていた。
    そこで、別名のどれかがIGDBの名前や別名と一致すれば、そこから機種を借りる。
    2026-09-19の時点で、手で足した116件のうち65件がこれで埋まった。

    残り（スマホ専用ゲームなど）は data/platforms.json に手で書く。
    空のリスト [] は「PCでもゲーム機でも売っていない」＝店のリンクを出さない。
    """
    out, by = {}, {}
    for g in catalogue():
        if not g.get("p"):
            continue
        out[g["name"]] = g["p"]
        for nm in [g["name"]] + list(g.get("alias") or []) + \
                  ([g["jp"]] if g.get("jp") else []):
            by.setdefault(compact(nm), g["p"])
    for game, aliases in (read_json(DATA / "aliases.json", {}) or {}).items():
        if out.get(game):
            continue
        for nm in [game] + list(aliases):
            p = by.get(compact(nm))
            if p:
                out[game] = p
                break
    out.update(read_json(DATA / "platforms.json", {}) or {})
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


# 括弧の中を、さらに「本物の区切り」で割るための字（2026-11-05 たろちんさん）
#
# なぜ要るか。**2字のゲーム名は、括弧まるごとのときしか当たらない。**
# `Index.add` は `len(c) >= 3` の別名しか部分一致の棚に入れないので、
# 『雀魂』は `exact`（括弧の中身と丸ごと一致）でしか拾えない。
# ところが実際の題は、括弧の中に別の字が混ざっているほうが多かった。
#
#     【#雀魂 #段位戦 】玉の間段位戦…       ← 淡雪花奏さん（連続配信790日台）
#     【 麻雀 / 雀魂 】雀魂杯で戦った4人で…  ← 緑青くれはさん
#     昇段戦、聖に戻る！【麻雀/雀魂 /ルイス・キャミー/にじさんじ】
#
# 2026-11-05に数えたら、**『雀魂』を含む題445本のうち176本（4割）が
# 落ちていた。** 毎日打っている常連ほど題の形が決まっているので、
# 同じ形で何十本も落ち続けていたことになる。
#
# ★**割るのは `#` `/` `｜` `、` `,` だけ。空白では割らない。**
#   空白で割ると【Dead by Daylight】が「Dead」「by」「Daylight」に、
#   【Among Us】が「Among」「Us」になって、短い英単語が
#   別のゲームの名前と丸ごと一致しうる。**そこまでやる必要はない。**
#
# ★**`・` でも割らない。** 『ロマンシング サ・ガ2』『ルイス・キャミー』の
#   ように、名前の中に入っている字なので。
#
# ★**元の括弧はそのまま残す。** 割ったほうだけにすると
#   【Dead by Daylight】のような「区切りを含まない長い名前」が消える。
#
# ★★★**割ったぶんで当たってよいのは、手で登録した別名だけ**（下の `sub` 印）。
#   最初に区切りだけ入れて全43,166本で測ったら、**新262本・失0本・移26本**で、
#   数だけ見れば大当たりだった。**中を読んだら、移った26本の大半が間違い。**
#
#     BW   → Black & White     『ポケットモンスターブラック/BW』が9本（ポケモンBW）
#     PS2  → PlanetSide 2      『悪代官3／PS2』（プレイステーション2）
#     ROM  → Runes of Magic    『ROM/初見コメント歓迎』（事務所の名前）
#     PS   → Paper Strike      『Steam/PS/Switch/Xbox』（売り場の名前）
#     PE   → Parasite Eve      『PE/Xbox/Win10/PS 対応』（Pocket Edition）
#     WoW  → World of Warcraft 『World of Warshipsみんなで遊ぼう【WoW/…】』
#     TA   → Total Annihilation『1時間本気でTA練習』（タイムアタック）
#     BIOHAZARD → バイオハザード 『BIOHAZARD/バイオハザード6』が10本（無印に化けた）
#     ソラ  → Sora             『バステン/ソーラ/クミ』（配信者の名前）
#
#   **どれもカタログ由来の名前。**そしてこちらが拾いたい『雀魂』は、
#   `aliases.json` に手で書いた行（pop 10^9）だった。線はここで引ける。
#
#   **割ったぶんは、手で登録した名前にだけ当てる。**
#   カタログ由来の名前は、これまでどおり**括弧まるごとのとき**だけ当たる。
SEG_SEP = re.compile(r"[#＃/／｜|、,]+")


def segments(title: str):
    """(中身, 括弧の強さ, 冒頭の括弧か, 割ったぶんか) を返す。

    括弧ひとつにつき、**中身まるごと**と、**区切りで割ったぶん**を返す。
    割ったぶんも同じ強さ・同じ「冒頭か」を持つ（中身は同じ括弧なので）。
    4つめが True のものは、**手で登録した別名にしか当たらない。**
    """
    m0 = LEAD_RE.match(title)
    lead_at = m0.end() - 1 if m0 else -1
    out = []
    for op, cl, pri in BRACKETS:
        pat = re.escape(op) + r"([^" + re.escape(op + cl) + r"]{1,60})" + re.escape(cl)
        for m in re.finditer(pat, title):
            inner = m.group(1).strip()
            lead = m.start() == lead_at
            out.append((inner, pri, lead, False))
            parts = [x.strip() for x in SEG_SEP.split(inner) if x.strip()]
            if len(parts) >= 2:
                out += [(x, pri, lead, True) for x in parts]
    out.append((title, 0, False, False))
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
    for seg, pri, lead, sub in segments(title):
        c = compact(seg)
        if pri > 0 and looks_like_noise(c, idx.ng):
            continue
        hit = idx.find(seg, strict=(pri == 0), curated_only=sub)
        if hit:
            g, ln, exact = hit
            # 冒頭の括弧を最優先にする。ゲーム名でない冒頭括弧（【ホロライブ】等）は
            # そもそもここに来ないので、この加点で誤判定が増えることはない。
            cands.append((pri * 100 + (150 if lead else 0)
                          + ln + (50 if exact else 0), g))
    if cands:
        cands.sort(reverse=True)
        win = cands[0][1]
        # ★題の中に「もっと長い正式名」も書いてあるとき、そちらを採る（2026-11-09）。
        #
        #   【ロマサガ2】難易度ロマンシング！…『ロマンシング サガ2 リベンジオブザセブン』Switch版
        #
        # 冒頭の括弧が +150 点もらうので、**題にはっきり書いてある長いほうが負ける。**
        # 11-01に決めた「裸の `ロマサガ2` は原作」はそのまま正しい。
        # これは**裸ではないのに負けている**ときの話で、別の問題。
        #
        # 点の付け方そのものは触らない。**手で書いた組のときだけ**入れ替える。
        # 組は data/長いほうを採る.json にあり、**両方が同じ題に出ているときしか効かない。**
        # check_series.py の「題の中に、入り先より長い別のゲーム名が書いてある」が
        # 候補を出してくれるので、人が見て決めた組だけをそこに足す。
        other = prefer_long().get(win)
        if other and any(g == other for _s, g in cands):
            win = other
        return win, "dict"
    if fallback:
        seg = leading_bracket(title, idx.ng)
        if seg:
            return seg, "unknown"      # 自動採用せず「確認待ち」に回す印
    return None, "none"
