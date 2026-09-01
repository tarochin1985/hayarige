#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""集計してサイトを書き出す。fetch_daily.py のあとに動かす。

出力: site/index.html と site/data.json
"""
import html
import math, re
from collections import defaultdict, Counter
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, quote_plus
from common import DATA, SITE, JST, log, read_json, write_json, today
import match as M
from check_column import load_valid

DAYS = 7
MIN_FOR_MOMENTUM = 3          # 急上昇の対象にする最低本数（少数のブレを弾く）
MIN_HISTORY = 4               # 急上昇を出すのに必要な「実データのある日数」
W = {"videos": 0.30, "channels": 0.35, "views": 0.35}


def load_all(days_back=30):
    """収集ファイルを全部読んで、動画IDで重複を除いた1本のリストにする。

    収集は毎回「直近48時間」を取り直すので、同じ動画が複数のファイルに入る。
    再生数はいちばん大きい（＝いちばん新しく取った）ものを採用する。

    戻り値は (動画リスト, 収集した日のリスト)。
    """
    best, runs = {}, []
    for f in sorted((DATA / "daily").glob("*.json")):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", f.stem):
            continue                      # .gitkeep.json などの置き石は読まない
        rec = read_json(f, None)
        if rec is None:
            continue
        runs.append(f.stem)
        for v in rec.get("videos", []):
            cur = best.get(v["id"])
            if cur is None or v.get("views", 0) >= cur.get("views", 0):
                best[v["id"]] = v
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


def tally(videos, idx):
    games = defaultdict(lambda: {"videos": 0, "sigs": set(), "channels": set(),
                                 "views": 0, "streams": [], "titles": [],
                                 "orgs": defaultdict(int)})
    unknown = []
    for v in videos:
        g, how = M.extract(v["title"], idx, fallback=True)
        if how == "dict":
            e = games[g]
            e["videos"] += 1
            e["sigs"].add(series_sig(v.get("channel_id"), v["title"]))
            e["channels"].add(v["channel_id"])
            e["views"] += v.get("views", 0)
            e["titles"].append(v["title"])
            e["orgs"][v.get("affiliation") or "個人・その他"] += 1
            if len(e["streams"]) < 12:
                e["streams"].append({"t": v["title"], "c": v["channel"],
                                     "u": f"https://www.youtube.com/watch?v={v['id']}",
                                     "th": v.get("thumb", ""), "v": v.get("views", 0)})
        elif how == "unknown":
            unknown.append({"title": v["title"], "guess": g, "channel": v["channel"],
                            "u": f"https://www.youtube.com/watch?v={v['id']}"})
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


def ssr_pick(col):
    """コラム。サイトでいちばん読まれる部分なので、必ずHTMLに出す。"""
    if not col:
        return ""
    parts = []
    if col.get("hero"):
        parts.append(f'<img class="heroimg" src="{e(col["hero"])}" alt="" loading="lazy">')
    body = ['<div class="ptxt">', '<span class="badge">PICK UP</span>',
            f'<div class="g">{e(col.get("game"))}</div>',
            f'<div class="hl">{e(col.get("headline"))}</div>',
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


def watched_channels():
    """毎日見に行っているチャンネル数。説明ページに出すために数える。"""
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
    return n


def about_html(cfg, n_channels):
    """このサイトについて。数字の出どころと、数えていないものを書く。"""
    lo = int(cfg.get("min_subscribers") or 0)
    jp = float(cfg.get("min_japanese_ratio", 0.5))
    return f"""
<h2>このサイトは何か</h2>
<p class="lead">VTuber・ゲーム実況者がYouTubeに出している配信のタイトルを毎日集めて、
いまどのゲームが配信されているかをランキングにしています。
「次、何のゲーム配信する？」と考えている配信者のために作りました。</p>
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

<h2>どう数えているか</h2>
<p>順位は、次の3つを合わせた独自のスコアで決めています。</p>
<ul>
  <li><b>配信者数</b> ── そのゲームを配信したチャンネルが何件あったか</li>
  <li><b>再生数</b> ── その合計</li>
  <li><b>配信数</b> ── 配信・動画が何本あったか</li>
</ul>
<p>ひとりがたくさん投稿しただけで上位に来ないよう、<b>何人が配信したか</b>をいちばん重く見ています。
「今このゲームがアツい」は、直近数日とくらべて増えたタイトルです。
倍率だけでは大きさが分からないので、実数（ふだん◯件 → 今日◯件）も並べています。</p>

<h2>数えていないもの</h2>
<ul>
  <li><b>Shorts</b>（90秒以下の動画）</li>
  <li><b>切り抜き</b>（タイトルや チャンネル名から判定）</li>
  <li><b>同じ配信者が同じ日に出した続きもの</b> ── 1本の配信を分割した動画などは1件として数えます。
      別の日に続くシリーズは、その日ごとに数えます</li>
  <li><b>日本語以外で配信しているチャンネル</b> ── 事務所は問いません</li>
  <li><b>ゲーム名を判定できなかった配信</b> ── 推測では埋めません</li>
</ul>

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
    on_pc = (not plat) or ("pc" in plat)
    on_console = (not plat) or ("console" in plat)

    steam = ("https://store.steampowered.com/search/?term=" + quote(name)) if on_pc else None
    amazon = None
    tag = (cfg.get("amazon_tag") or "").strip()
    if tag and on_console and cfg.get("amazon_in_ranking"):
        amazon = ("https://www.amazon.co.jp/s?k=" + quote_plus(name)
                  + "&tag=" + quote_plus(tag))
    return steam, amazon


def compute_rows(videos, idx, disp, override, hist, day_names, momentum_ready,
                 plats=None, cfg=None):
    """その日の動画リストから、ランキングの行を作る。"""
    plats, cfg = plats or {}, cfg or {}
    games, unknown = tally(videos, idx)
    rows = []
    for name, e in games.items():
        rows.append({"game": choose_name(name, disp.get(name), e["titles"], override),
                     "canonical": name, "videos": len(e["sigs"]), "raw": e["videos"],
                     "channels": len(e["channels"]), "views": e["views"],
                     "streams": sorted(e["streams"], key=lambda s: -s["v"])[:8],
                     "orgs": dict(sorted(e["orgs"].items(), key=lambda x: -x[1])),
                     "spark": [hist[d].get(name, 0) if d in hist else None
                               for d in day_names]})
    if rows:
        mx_v = max(r["videos"] for r in rows) or 1
        mx_c = max(r["channels"] for r in rows) or 1
        logs_ = [math.log10(1 + r["views"]) for r in rows]
        lo, hi = min(logs_), max(logs_)
        for r in rows:
            r["p_videos"] = round(r["videos"] / mx_v * 100)
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
        g, _ = tally(vids, idx)
        hist[day] = {k: len(v["sigs"]) for k, v in g.items()}
    momentum_ready = len(have) >= MIN_HISTORY

    rows, unknown = compute_rows(today_videos, idx, disp, override,
                                 hist, day_names, momentum_ready, plats, cfg)
    if not rows:
        log("今日のデータからゲームを検出できませんでした。処理を続けます。")

    rising = sorted([r for r in rows if r["videos"] >= MIN_FOR_MOMENTUM
                     and (r["growth"] or 0) > 1.25],
                    key=lambda r: -r["growth"])[:3] if momentum_ready else []
    # 急上昇が出せない間は「今日いちばん多くの配信者が触ったゲーム」を代わりに出す
    spread = sorted(rows, key=lambda r: (-r["channels"], -r["videos"]))[:3]

    # 検証を通らないコラムは載せない。無理に載せるより、無いほうがいい。
    column = load_valid(DATA / "columns" / f"{today()}.json", log)
    if column and column.get("buy"):
        column["buy"] = dict(column["buy"],
                             u=amazon_tagged(column["buy"].get("u", ""),
                                             (cfg.get("amazon_tag") or "").strip()))
    if column:
        # コラムの画像とSteamリンクを、コラム自身に持たせる。
        # 以前は表示側でランキング30位以内から同名を探していたので、
        # 取り上げたゲームが31位以下に落ちた瞬間に画像が消えていた
        # （8/29のみんなのGOLF）。順位に関係なく出したいので、
        # 30位で切る前の全ゲーム（rows）から引く。
        cr = next((r for r in rows if r["game"] == column["game"]), None)
        if cr:
            st = cr.get("streams") or []
            if st and st[0].get("th"):
                column["hero"] = st[0]["th"]
            if cr.get("steam"):
                column["steam"] = cr["steam"]
        if not column.get("hero"):
            # ランキングに1本も無いゲーム（配信が終わって24時間を過ぎた等）でも、
            # 出典のYouTube動画からサムネイルを作れる。
            for src in column.get("sources") or []:
                m = re.search(r"(?:youtube\.com/watch\?v=|youtu\.be/)([\w-]{11})",
                              str(src.get("u", "")))
                if m:
                    column["hero"] = f"https://i.ytimg.com/vi/{m.group(1)}/mqdefault.jpg"
                    break

    payload = {
        "mode": "day",
        "date": today(),
        "column": column,
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
        """depth はサイト直下から何階層下か。リンクの相対パスに使う。"""
        d = dict(data, paths={"home": "../" * depth or "./",
                              "archive": ("../" * depth or "./") + "archive/"})
        p = SITE / path
        p.parent.mkdir(parents=True, exist_ok=True)
        home = "../" * depth or "./"
        # そのページ自身のURL。index.html は省いて、ディレクトリの形にする。
        page = "" if path == "index.html" else path.replace("index.html", "")
        rows_ = data.get("ranking") or []
        col_ = data.get("column")
        p.write_text(tpl.replace("__DATA__", json.dumps(d, ensure_ascii=False))
                        .replace("__HOME__", home)
                        .replace("__PAGEURL__", f"{site_url}/{page}" if site_url else "")
                        .replace("__SITE__", site_url)
                        # JavaScriptなしでも読める中身。JSが動けば同じ内容で描き直される
                        .replace("__PICKDISP__", "" if col_ else "display:none")
                        .replace("__SSR_PICK__", ssr_pick(col_))
                        .replace("__SSR_CARDS__", ssr_cards(rows_))
                        .replace("__SSR_ROWS__", ssr_rows(rows_))
                        .replace("__PAGEBODY__", data.get("page_body", "")),
                     encoding="utf-8")

    render("index.html", payload, 0)
    # その日の記録を、消えない住所に残す
    render(f"d/{today()}/index.html", dict(payload, view="archive"), 2)

    # ---- 管理用ページ（トップからはリンクしない） ----
    # よく出るタイトルを data/aliases.json に足していくための作業台。
    unk_counts = Counter(u["title"] for u in unknown)
    seen, unk_rows = set(), []
    for u in unknown:
        key = M.compact(u["title"])[:24]
        if key in seen:
            continue
        seen.add(key)
        unk_rows.append(dict(u, n=unk_counts[u["title"]]))
    unk_rows.sort(key=lambda u: -u["n"])
    leads = find_leads(today_videos, rows, hist, day_names)
    recent_cols = []
    for f in sorted((DATA / "columns").glob("*.json"))[-14:]:
        c = read_json(f, None) or {}
        if c.get("game"):
            recent_cols.append({"date": f.stem, "game": c["game"],
                                "headline": c.get("headline", "")})
    admin = {"mode": "admin", "date": today(),
             "generated": payload["generated"], "unknown": unk_rows,
             "leads": leads, "recent_columns": recent_cols[::-1]}
    render("admin/index.html", admin, 1)
    write_json(SITE / "admin" / "unknown.json", admin)
    # robots.txt で /admin/ を検索避けしているが、それだと外から読む手段まで
    # 塞がってしまう。中身は公開データの集計でしかないので、機械で読む用は
    # 直下にも置く（トップからはリンクしない）。
    write_json(SITE / "leads.json",
               {"date": today(), "generated": payload["generated"],
                "leads": leads, "recent_columns": recent_cols[::-1]})

    # ---- アーカイブ一覧を更新する ----
    idx_path = DATA / "archive_index.json"
    entries = {e["date"]: e for e in (read_json(idx_path, []) or [])}
    entries[today()] = {
        "date": today(),
        "videos": payload["totals"]["videos"],
        "channels": payload["totals"]["channels"],
        "games": payload["totals"]["games"],
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
    recent = sorted(buckets)[-7:]
    # 収集を始める前の日は「その日の記録」として不完全なので載せない。
    # 収集は48時間ぶんを取るが、控えめに1日ぶんだけ信用する。
    cover_from = ((datetime.strptime(runs[0], "%Y-%m-%d") - timedelta(days=1))
                  .strftime("%Y-%m-%d") if runs else "9999-12-31")
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
        past_rows, _ = compute_rows(vids, idx, disp, override, {}, [], False,
                                    plats, cfg)
        if not past_rows:
            continue
        col = read_json(DATA / "columns" / f"{day}.json", None)
        entries[day] = {
            "date": day, "videos": len(vids), "games": len(past_rows),
            "channels": len({v["channel_id"] for v in vids}),
            "top": [{"game": r["game"], "videos": r["videos"], "channels": r["channels"]}
                    for r in past_rows[:5]],
            "column": {"game": col["game"], "headline": col["headline"]} if col else None,
        }
        render(f"d/{day}/index.html",
               {"mode": "day", "view": "archive", "date": day, "column": col,
                "generated": "", "days": [], "rising": [], "spread": past_rows[:3],
                "momentum": {"ready": False, "days": 0, "need": MIN_HISTORY},
                "totals": {"videos": entries[day]["videos"], "games": len(past_rows),
                           "channels": entries[day]["channels"]},
                "ranking": past_rows[:30]}, 2)
        added += 1
    if added:
        log(f"過去 {added} 日分のページを作り直しました")

    archive = sorted(entries.values(), key=lambda e: e["date"], reverse=True)
    write_json(idx_path, archive)
    render("archive/index.html",
           {"mode": "archive", "date": today(), "archive": archive}, 1)

    # ---- 説明ページ ----------------------------------------------------
    # 数字を出すサイトなので、どう数えているかが読めることが信用に直結する。
    # 「Shortsと切り抜きは除く」「連番は1件」などは、書いていなければ
    # 誰にも伝わらない。
    render("about/index.html",
           {"mode": "page", "date": today(), "subtitle": "このサイトについて",
            "generated": payload["generated"],
            "page_body": about_html(cfg, watched_channels())}, 1)

    # ---- sitemap.xml ---------------------------------------------------
    # 日付ごとの記録は日が経つほど増える資産だが、たどり着く道が
    # トップからのリンクしかない。存在をまとめて知らせる。
    if site_url:
        urls = [(f"{site_url}/", "daily", "1.0"),
                (f"{site_url}/about/", "monthly", "0.5"),
                (f"{site_url}/archive/", "daily", "0.6")]
        urls += [(f"{site_url}/d/{a['date']}/", "monthly", "0.4") for a in archive]
        body = "".join(
            f"<url><loc>{u}</loc><changefreq>{f}</changefreq><priority>{pr}</priority></url>"
            for u, f, pr in urls)
        (SITE / "sitemap.xml").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            + body + "</urlset>", encoding="utf-8")
        rb = SITE / "robots.txt"
        txt = rb.read_text(encoding="utf-8") if rb.exists() else "User-agent: *\nAllow: /\n"
        if "Sitemap:" not in txt:
            rb.write_text(txt.rstrip() + f"\n\nSitemap: {site_url}/sitemap.xml\n",
                          encoding="utf-8")
        log(f"sitemap.xml を書き出しました（{len(urls)} ページ）")

    log(f"サイトを書き出しました: {len(rows)} タイトル / 急上昇 {len(rising)} 件 "
        f"/ 確認待ち {len(unknown)} 件")
    log(f"アーカイブ: {len(archive)} 日分（site/d/{today()}/ に本日分を保存）")


if __name__ == "__main__":
    main()
