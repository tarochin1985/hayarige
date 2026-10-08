#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""コラムの品質チェック。

このサイトで一番読まれる部分なので、機械で守れるところは機械で守る。
ここを通らなかったコラムは、サイトに出ない（その日はコラム無しになる）。
出さない日があるのは失敗ではない。書くことが無い日に無理に書くほうが失敗。

単体でも動く:  python scripts/check_column.py data/columns/2026-08-27.json
"""
import json
import re
import sys
from pathlib import Path

# 記録ページの置き場所。「初めて」を確かめるのに使う。
SITE_D = Path(__file__).resolve().parent.parent / "site" / "d"
# 集めた配信そのもの。見出しに付けた企画のタグが実在するかを確かめるのに使う。
DATA = Path(__file__).resolve().parent.parent / "data"

# 「当サイトの集計に入ったのは今日が初めて」と書いてよいのは、
# 本当に過去1日も出ていないときだけ。
# 2026-09-12に、直近3日ぶんしか見ずに How to Fish を「初めて」と書いて間違えた。
# 実際には 8/26・8/27・8/28・9/1・9/6 にも入っていた。
# 人が数え忘れる種類の間違いなので、機械で確かめる。
FIRST_RE = re.compile(
    r"(当サイト|集計|ランキング)[^。]{0,40}?(初めて|初登場|今回が初)"
    r"|(初めて|初登場|今回が初)[^。]{0,40}?(集計|ランキング)")


def _today():
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) + timedelta(hours=9)).strftime("%Y-%m-%d")


def seen_days(game, before):
    """そのゲームがランキングに入った日を古い順に返す（before より前だけ）。

    記録ページに埋め込んである当日ぶんのデータを読む。30日を過ぎた日でも
    ゲーム名と件数は残っているので、全期間を数えられる。
    """
    out = []
    if not game or not SITE_D.is_dir():
        return out
    for d in sorted(SITE_D.iterdir()):
        if not d.is_dir() or (before and d.name >= before):
            continue
        f = d / "index.html"
        if not f.is_file():
            continue
        try:
            h = f.read_text(encoding="utf-8")
            i = h.index("const DATA = ") + len("const DATA = ")
            obj, _ = json.JSONDecoder().raw_decode(h[i:])
        except (ValueError, OSError):
            continue
        if any(r.get("game") == game for r in (obj.get("ranking") or [])):
            out.append(d.name)
    return out

# 裏が取れていないことを、取れているように見せてしまう言い回し。
# 「〜という事実」だけを書くルールを、言葉のレベルで縛る。
HEDGE = [
    "と思われる", "と見られる", "とみられる", "だろう", "かもしれない",
    "のようだ", "らしい。", "considered", "推測", "おそらく", "うわさ", "噂",
    "話題を呼んで", "が話題", "注目を集めて", "盛り上がりを見せて",
    "人気が高まって", "とされる", "という声も", "ではないだろうか",
]

# 出典に使ってはいけない場所。まとめサイトは話題の当たりをつけるためだけに使い、
# 根拠には必ず一次ソース（公式・ゲームメディア・実際の配信）を当てる。
BAD_SOURCE = [
    "matome", "blog.livedoor", "2ch", "5ch", "openwork", "togetter",
    "hatenablog", "note.com/", "wikiwiki", "seesaa", "fc2", "ameblo",
    "search.yahoo.co.jp/realtime", "vtuber-matome", "vtubermatome",
]

MIN_BODY, MAX_BODY = 120, 480
# 「今日の見どころ」（notes）。急上昇のカードの上に並ぶ短い行。
# 長くすると、そこだけで読み終わってしまってカードを見なくなる。
# 1行で1つのことだけ書く長さに抑える（2026-09-26）。
NOTES_MAX, MIN_NOTE, MAX_NOTE = 4, 12, 80


# 見出しの先頭に付ける企画のタグ。「#タグ名」でも「『#タグ名』」でも拾う。
HEAD_TAG = re.compile(r"^[「『【]?\s*[#＃]([^\s　」』】#＃]{2,40})\s*[」』】]?[\s　]*")


def head_tag(head):
    """見出しの先頭の「#タグ名」を (タグ, 残りの見出し) に分ける。

    （2026-10-04 たろちんさんと決めました）
    企画・大会の回は、見出しの頭に「#マイクラ肝試し2026」のように付けます。
    Xの投稿文にはこの見出しがそのまま載るので、**そこでハッシュタグとして効く**。
    タグを追っている人の目に入るのがねらいで、同時に読む人にも
    何の企画の話かがすぐ伝わります。
    """
    m = HEAD_TAG.match(str(head or ""))
    return (m.group(1), head[m.end():].strip()) if m else ("", str(head or "").strip())


def tag_check(tag, day):
    """そのタグが、その日の配信タイトルで本当に使われているかを数える。

    **思い出して書いたタグは、たいてい少し違う。** 年号が違う、「！」が余る、
    略されている。少し違うだけで、Xでは誰も居ないタグに投稿することになり、
    付けないより悪い。そこで**その日集めたタイトルの中に実際にあるか**を見る。

    data/daily/ は直近30日ぶんしか残らないので、その日のファイルが無ければ
    何も言わない（古いコラムを後から確かめ直すときに、嘘の警告を出さないため）。
    """
    f = DATA / "daily" / f"{day}.json"
    if not f.is_file():
        return []
    try:
        vids = (json.loads(f.read_text(encoding="utf-8")) or {}).get("videos") or []
    except (ValueError, OSError):
        return []
    low = tag.lower()
    chans = {v.get("channel") for v in vids if low in str(v.get("title", "")).lower()}
    if not chans:
        return [f"「#{tag}」は、その日の配信タイトルに1件も出てきません。"
                "綴りを配信タイトルからそのまま写してください"
                "（居ないタグに投稿すると、付けないより悪くなります）"]
    if len(chans) < 2:
        return [f"「#{tag}」を使っているのは {len(chans)} チャンネルだけです。"
                "企画のタグとして正しいか、配信タイトルで確かめてください"]
    return []


# ------------------------------------------------------------ 見出しの形
# なぜ要るか（2026-10-08 たろちんさん）
#
#   > 「圧縮型」と「落差型」は型としてはいいけど、例として出しているものが
#   > 単純に面白くない。理由としてはワードチョイスが硬すぎて
#   > せっかくの面白さが消えている。構文や文体のせいかもしれない。
#
# 42本を数えたら、**38本（90%）が「A、B」の対句**だった。
# 口語の縮約は9%、読者への話しかけは4%で、その4%は両方たろちんさんの指定。
# **こちらが自分で出したものは0本。** 知らないのではなく、毎朝まっさらな状態から
# 同じ安全な形に落ちている。朝の窓は前日に何を書いたかを知らないので、
# **直近の見出しを並べて見せるのが、いちばん効く手当てになる。**
# 「てる」「てた」だけを見ると、『建てる』『捨てた』のような普通の動詞まで
# 口語と数えてしまう（2026-10-08に「まず工場を建てる」で出た）。
# 縮約だと言い切れる形だけを見る。拾い逃しは害にならないが、
# **札が嘘をつくのは害になる。**
SHUKU = re.compile(r"って[たるん]|んでる|んでた|じゃ|ちゃ|とか|っぽい|すぎ|なきゃ|ねえ|やべ")
YOBI = re.compile(r"[?？]$|[のねよなぞ]$|んだ$|かも$|でしょ$")
IIKIRI = re.compile(r"(う|く|ぐ|す|つ|ぬ|ぶ|む|る|た|だ|ない|ます|ません)$")


def head_shape(head):
    """見出しの文の形を、短い札にする。中身の良し悪しは見ない。"""
    _, body = head_tag(str(head or ""))
    f = []
    f.append("対句" if "、" in body else "一文")
    if re.search(r"[「『]", body):
        f.append("引用")
    if YOBI.search(body):
        f.append("話しかけ")
    elif IIKIRI.search(body):
        f.append("言い切り")
    else:
        f.append("体言止め")
    if SHUKU.search(body):
        f.append("口語")
    return "＋".join(f)


def recent_heads(day, n=5):
    """直近の見出しを (日付, 見出し, 形) で返す。その日より前だけ。"""
    out = []
    d = DATA / "columns"
    for f in sorted(d.glob("2026-*.json"), reverse=True) if d.is_dir() else []:
        if f.stem >= str(day):
            continue
        try:
            c = json.loads(f.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        h = str(c.get("headline") or "").strip()
        if h:
            out.append((f.stem, h, head_shape(h)))
        if len(out) >= n:
            break
    return out


def shape_check(head, day):
    """直近と同じ形ばかりになっていないかを見る。"""
    if not head or not day:
        return []
    mine = head_shape(head)
    rec = recent_heads(day)
    same = [r for r in rec if r[2] == mine]
    out = []
    if len(same) >= 3:
        out.append(f"見出しが「{mine}」で、直近{len(rec)}日のうち{len(same)}日が同じ形です。"
                   "読点で割らない／言い切りをやめる／口語にする／人を入れる、"
                   "のどれかで形を変えてください")
    elif mine.startswith("対句") and "口語" not in mine and "引用" not in mine:
        out.append(f"見出しが「{mine}」です。**この形がいちばん出やすく、"
                   "いちばん硬くなります。** ほかの形も1本作って見比べてください")
    return out


def quote_check(head, day):
    """見出しの鍵括弧の中が、その日の配信タイトルに実在するかを見る。

    **チャンネル数は条件にしない**（2026-10-08 たろちんさん）。

      > 多数派の凡庸なコメント、フレーズよりもむしろ
      > 12人中1人のパンチラインを引用するほうが強い

    だから数では測らない。見るのは「その字が本当に在るか」だけ。
    在れば誰の言葉かを出して、本文で明かせるようにする。
    """
    _, body = head_tag(str(head or ""))
    qs = [q for q in re.findall(r"[「『]([^」』]{3,40})[」』]", body)]
    if not qs or not day:
        return [], []
    f = DATA / "daily" / f"{day}.json"
    if not f.exists():
        return [], []
    try:
        vids = (json.loads(f.read_text(encoding="utf-8")) or {}).get("videos", [])
    except (ValueError, OSError):
        return [], []
    warn, note = [], []
    for q in qs:
        hit = [v for v in vids if q in str(v.get("title") or "")]
        if hit:
            chs = sorted({str(v.get("channel") or "") for v in hit})
            note.append(f"「{q}」は{chs[0]}さんの題にあります"
                        + (f"（ほか{len(chs) - 1}チャンネルも同じ字）" if len(chs) > 1 else "")
                        + "。本文で誰の言葉か分かるように書いてください")
        else:
            warn.append(f"見出しの「{q}」が、その日の配信タイトルに見つかりません。"
                        "引用のつもりなら綴りを確かめてください。"
                        "ネタ（ミーム）として使っているなら、"
                        "その土台になる事実が本文にあるか確かめてください")
    return warn, note


def style(col, day=""):
    """書き方の注意を返す。**これがあってもサイトには出す。**

    validate() のほうは「出してはいけない」ものだけを見ている（裏取り・出典・
    リンクの正しさ）。見出しの長さのような書き方の話でその日のコラムが
    まるごと消えるのは、直したい問題よりも大きな損になる。
    だから警告として分け、書いている最中に気づける形にしてある。
    """
    if not isinstance(col, dict):
        return []
    out = []
    # 見出しは短いキャッチコピー。説明の一文になっていると、
    # Xの画像で2〜3行を食いつぶして本文が小さくなる。
    head = str(col.get("headline", "")).strip()
    if head:
        # 先頭の「#タグ名」は見出しの本体ではないので、長さに数えない。
        # 「上限を30字から45字に上げる」ではなく**タグのぶんだけ外す**形にしてある。
        # 上げてしまうと、タグが無い日まで長い見出しが通るようになる（2026-10-04）。
        tag, body = head_tag(head)
        if not (8 <= len(body) <= 30):
            out.append(f"見出しが {len(body)} 字です（8〜30字のキャッチコピーにしてください）"
                       + ("。先頭の「#タグ」は数えていません" if tag else ""))
        if head.endswith("。"):
            out.append("見出しが説明の一文になっています。句点で終わらない短い言葉にしてください")
        # ゲーム名の重複はタグを外した本体だけで見る。企画のタグには
        # 「#マイクラ肝試し2026」のようにゲーム名が入っていることがあり、
        # それは企画の正式な名前なので直す必要がない。
        game = str(col.get("game", "")).strip()
        if game and game in body:
            out.append(f"見出しにゲーム名が入っています（「{game}」）。"
                       "見出しのすぐ上にゲーム名が大きく出るので、重ねないでください")
        if tag:
            out += tag_check(tag, day or str(col.get("date", "")) or _today())
        _day = day or str(col.get("date", "")) or _today()
        out += shape_check(head, _day)
        out += quote_check(head, _day)[0]

    # 「初めて」と書いているなら、本当に初めてかを数えて確かめる。
    # 書いていない日は記録ページを読みに行かないので、普段の負担はない。
    text = str(col.get("body", "")) + " " + str(col.get("headline", ""))
    if FIRST_RE.search(text):
        # day はコラムの日付（ファイル名から取る）。その日より前だけを数える。
        # ここを空にすると当日の記録ページまで数えてしまい、本当に初めての
        # ゲームを「前にも出ている」と誤って弾いてしまう。
        days = seen_days(str(col.get("game", "")).strip(),
                         day or str(col.get("date", "")) or _today())
        if days:
            # ここは「間違い」と断定しない。「昨日が初めて」のように、
            # 過去に出ていても正しい書き方があるため。事実だけを出して、
            # 書いた本人に確かめさせる。
            last = f"{int(days[-1][5:7])}月{int(days[-1][8:10])}日"
            first = f"{int(days[0][5:7])}月{int(days[0][8:10])}日"
            out.append(
                f"「初めて」と書いています。このゲームがランキングに入った日は"
                f"{first}が最初で、直近は{last}、全部で{len(days)}日あります。"
                "書いた内容と合っているか確かめてください"
                "（本当に今日が初めてなら、この行は出ません）")
    return out


def info(col, day=""):
    """止めるほどではないが、書く前に知っておきたいこと。

    いまのところ1つだけ。そのゲームが過去に何日ランキングに入っていたか。
    本文を「どんなゲームか」から始めるか「何が起きたか」から始めるかは、
    読者がそのゲームを知っているかで決まる（EDITORIAL.md 5章）。
    その判断材料になる。
    """
    if not isinstance(col, dict):
        return []
    game = str(col.get("game", "")).strip()
    days = seen_days(game, day or str(col.get("date", "")) or _today())
    _day = day or str(col.get("date", "")) or _today()
    # 見出しの手当て（直近の見出し・引用の裏取り）は、**初登場の日にも必ず出す。**
    # 初登場の日はいちばん形が固まりやすいのに、ここで早く返していたため
    # 出ていなかった（2026-10-08）。
    tail = (tag_hint(col, _day)
            + quote_check(str(col.get("headline") or ""), _day)[1]
            + head_history(_day))
    if not days:
        return [f"「{game}」が当サイトのランキングに入るのは今日が初めてです。"
                "読者も知らない可能性が高いので、どんなゲームかの説明から始めるのが無難です"
                ] + tail
    first = f"{int(days[0][5:7])}月{int(days[0][8:10])}日"
    if len(days) <= 3:
        add = "まだ数日しか出ていません。どんなゲームかの説明から始めるのが無難です"
    elif len(days) >= 10:
        add = "常連です。読者も知っている前提で、何が起きたかから書き始めてよいです"
    else:
        add = "ときどき出てきます。どちらから書くかは中身で決めてください"
    return [f"「{game}」は過去{len(days)}日ランキングに入っています"
            f"（最初は{first}）。{add}"] + tail


def head_history(day):
    """直近5日の見出しと、その形を並べる。**毎回必ず出す。**

    朝の窓は前の日に何を書いたかを知らない。だから見本も注意書きも無しで
    毎日書くと、同じ形に戻る（42本で90%が「A、B」になっていた）。
    **並べて見せるだけで、少なくとも「また同じだ」には気づける。**
    """
    rec = recent_heads(day)
    if not rec:
        return []
    out = ["直近の見出しと、その文の形:"]
    for d, h, sh in rec:
        out.append(f"      {d[5:]} [{sh}] {h}")
    out.append("      ★今日はこれと違う形にしてください。"
               "型は EDITORIAL.md の見出しの章（引用型・圧縮型・落差型・ネタ型）")
    return out


# 一般語のタグ。企画の名前ではないので、見出しに付けても意味がない。
TAG_SKIP = {"vtuber", "新人vtuber", "個人勢", "ゲーム実況", "ゲーム配信", "切り抜き",
            "shorts", "live", "参加型", "視聴者参加型", "雑談", "初見歓迎", "顔出し",
            "ホロライブ", "にじさんじ", "ぶいすぽ", "ななしいんく", "pr", "ゲーム",
            "実況", "生配信", "配信", "ライブ", "歌枠", "作業用bgm"}
TAG_FIND = re.compile(r"[#＃]([^\s　#＃、。，．！？!?,.()（）\[\]【】「」『』/／|｜:：]{3,40})")


def tag_hint(col, day):
    """その日いちばん使われている企画のタグを教える（2026-10-04 たろちんさん）。

    企画・大会の回は、見出しの頭に「#タグ名」を付ける決まりにした
    （EDITORIAL.md 5章）。Xの投稿文でハッシュタグとして効かせるため。

    ただ**決まりを文章で書いただけでは、書く人が毎回思い出せない。**
    その日の配信タイトルからタグを数えて、使えるものがあるときだけ
    ここで名前を出す。綴りも実物をそのまま写したものになる。
    """
    head = str(col.get("headline", "")).strip()
    if head_tag(head)[0]:
        return []                      # もう付いている
    f = DATA / "daily" / f"{day}.json"
    if not f.is_file():
        return []
    try:
        vids = (json.loads(f.read_text(encoding="utf-8")) or {}).get("videos") or []
    except (ValueError, OSError):
        return []
    use = {}
    for v in vids:
        for t in set(TAG_FIND.findall(str(v.get("title", "")))):
            if t.lower() in TAG_SKIP:
                continue
            use.setdefault(t, set()).add(v.get("channel"))
    # 3チャンネル以上が同じタグを使っていれば、企画の可能性が高い
    top = sorted(((len(c), t) for t, c in use.items() if len(c) >= 3), reverse=True)
    if not top:
        return []
    names = "／".join(f"#{t}（{n}ch）" for n, t in top[:3])
    return ["その日よく使われていたタグ: " + names
            + "。企画の回なら、見出しの頭に「#タグ名」を付けてください"
            + "（EDITORIAL.md 5章。Xでハッシュタグとして効きます）"]


def drift_notes():
    """辞書の穴を、コラムを書く人にも見せる。

    2つある。ひとつは続編が前作と同じ行に数えられている疑い。
    もうひとつは「何人もが配信しているのに、ゲーム名と判定できていない名前」。
    後者は2026-09-20に『デスゲームの報告書』を19日間見落としていたのが
    分かって足した。管理ページを毎日開く運用になっていないので、
    コラムを書く前に必ず通るここにも出す。

    もとの説明（続編の件）:

    build_site.py が毎回調べて site/admin/unknown.json に書いている。
    ただし管理ページを毎日開く運用にはなっていないので、コラムを書く前に
    必ず通るここにも出す。順位そのものが狂っている可能性がある話なので、
    その日のコラムを書く前に気づけたほうがよい。
    """
    f = SITE_D.parent / "admin" / "unknown.json"
    if not f.is_file():
        return []
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []
    out = []
    # 辞書に無いかもしれない新作。何人が配信しているかの多い順で上位だけ。
    for x in (d.get("unknown") or [])[:5]:
        if (x.get("channels") or 0) >= 3:
            out.append(
                f"「{x.get('guess')}」を {x.get('channels')}チャンネルが配信していますが、"
                f"ゲーム名として判定できていません（{x.get('n')}本）。"
                "ゲームなら data/aliases.json に足すと、次から数に入ります")
    for x in (d.get("drift") or []):
        out.append(
            f"「{x.get('written')}」と書いている配信者が {x.get('channels')}人／"
            f"{x.get('of')}人いますが、いまは「{x.get('game')}」として数えています。"
            "別のゲームなら data/aliases.json に足す必要があります"
            "（順位が前作と合算されています）")
    return out


def validate(col):
    """出してはいけない理由のリストを返す。空なら掲載してよい。"""
    bad = []
    if not isinstance(col, dict):
        return ["JSONの形が違います（オブジェクトではありません）"]

    for k in ("game", "headline", "body"):
        if not str(col.get(k, "")).strip():
            bad.append(f"{k} が空です")

    body = str(col.get("body", ""))
    if body and not (MIN_BODY <= len(body) <= MAX_BODY):
        bad.append(f"本文が {len(body)} 字です（{MIN_BODY}〜{MAX_BODY} 字にしてください）")

    notes = col.get("notes")
    if notes is not None:
        if not isinstance(notes, list):
            bad.append("notes はリストにしてください（[\"…\", \"…\"]）")
            notes = []
        elif len(notes) > NOTES_MAX:
            bad.append(f"notes が {len(notes)} 行あります（{NOTES_MAX} 行までにしてください）")
        for n in (notes or []):
            n = str(n)
            if not (MIN_NOTE <= len(n) <= MAX_NOTE):
                bad.append(f"notes の行が {len(n)} 字です"
                           f"（{MIN_NOTE}〜{MAX_NOTE} 字にしてください）: {n[:24]}")
    note_text = " ".join(str(n) for n in (col.get("notes") or []))

    for w in HEDGE:
        if w in body or w in note_text or w in str(col.get("headline", "")):
            bad.append(f"推測を含む言い回しがあります: 「{w}」")

    buy = col.get("buy")
    if buy is not None:
        u = str((buy or {}).get("u", ""))
        if "amazon.co.jp" not in u and "store.steampowered.com" not in u:
            bad.append(f"buy のURLはAmazonかSteamの商品ページにしてください: {u!r}")
        elif "amazon.co.jp/s?" in u or "/s?k=" in u:
            bad.append("buy に検索結果のURLは使えません。商品ページ（/dp/...）を指定してください")

    # summary（3行要約）はツイート画像に使う。無くてもよいが、
    # 入れるなら短く。長い行は画像の中で読めない。
    sm = col.get("summary")
    if sm is not None:
        if not isinstance(sm, list) or len(sm) > 3:
            bad.append("summary は3行までのリストにしてください")
        else:
            for i, line in enumerate(sm, 1):
                n = len(str(line))
                if n < 8 or n > 42:
                    bad.append(f"summary の{i}行目が {n} 字です（8〜42字にしてください）")

    srcs = col.get("sources") or []
    if not srcs:
        bad.append("出典がありません。一次ソースを最低1つ付けてください")
    for s in srcs:
        u = str((s or {}).get("u", ""))
        if not re.match(r"^https?://", u):
            bad.append(f"出典のURLが不正です: {u!r}")
            continue
        for ng in BAD_SOURCE:
            if ng in u.lower():
                bad.append(f"まとめ・二次情報を出典にしています: {u}")
                break
    return bad


def load_valid(path, log=print):
    """検証を通ったコラムだけを返す。通らなければ None。"""
    p = Path(path)
    if not p.exists():
        return None
    try:
        col = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        log(f"コラムのJSONが壊れています（{p.name}）: {e}")
        return None
    bad = validate(col)
    if bad:
        log(f"コラムを掲載しません（{p.name}）。理由:")
        for b in bad:
            log(f"  - {b}")
        return None
    for w in style(col, p.stem):
        log(f"コラムの書き方の注意（{p.name}）: {w}")
    return col


def main():
    if len(sys.argv) < 2:
        print("使い方: python scripts/check_column.py <コラムのJSON>")
        return 2
    ok = True
    for arg in sys.argv[1:]:
        col = json.loads(Path(arg).read_text(encoding="utf-8"))
        day = Path(arg).stem
        bad, warn = validate(col), style(col, day)
        if bad or warn:
            ok = False
            print(("❌ " if bad else "⚠️  ") + arg)
            for b in bad:
                print(f"   - {b}")
            for w in warn:
                print(f"   ※ {w}（サイトには出ますが、直したほうがよいです）")
        else:
            print(f"✅ {arg}")
        # 合否とは関係のない参考情報。書き出しをどちらから始めるかの判断に使う
        for i in info(col, day):
            print(f"   ℹ️  {i}")
    # 辞書の穴。コラムの合否とは関係ないが、順位のほうが狂っている話なので出す
    for d in drift_notes():
        print(f"🔧 {d}")
    # 文字数を数えても、サイトでどう見えるかは分からない。
    # とくに「今日の見どころ」（notes）は、急上昇のカードと並んで初めて形になる。
    print(f"👀 見え方の確認: python3 scripts/preview_column.py {sys.argv[1]}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
