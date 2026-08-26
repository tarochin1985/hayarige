#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""まず最初に動かすもの。3つのキーが正しく使えるかだけを確かめます。

ここが通れば、あとの処理はほぼ確実に動きます。
"""
import sys
from common import YouTube, IGDB, log, DATA, read_json

print("=" * 60)
print(" ハヤリゲー セルフテスト")
print("=" * 60)

ok = True

# ---- 1. YouTube ----------------------------------------------------------
print("\n【1/3】YouTube APIキーを確認します …")
try:
    yt = YouTube()
    # ホロライブ公式チャンネルで1回だけ試す
    res = yt.channels(ids=["UCJFZiqLMntJufDCHc6bQixg"])
    items = res.get("items", [])
    if not items:
        print("  △ 接続はできましたが、結果が空でした。")
        ok = False
    else:
        ch = items[0]
        subs = ch["statistics"].get("subscriberCount", "?")
        print(f"  ✅ 成功　テスト取得: {ch['snippet']['title']}（登録者 {subs}）")
        print(f"     使用クォータ: {yt.used} ユニット（1日の上限 10,000）")
except SystemExit:
    raise
except Exception as e:
    print(f"  ❌ 失敗: {e}")
    ok = False

# ---- 2. IGDB -------------------------------------------------------------
print("\n【2/3】Twitchのキー（ゲーム辞書用）を確認します …")
try:
    ig = IGDB()
    # 評価件数の多いゲームを1本だけ取る。名前で探すと大文字小文字の違いで
    # 空振りするので、こちらのほうが確実。
    res = ig.query("games",
                   b"fields name,total_rating_count; "
                   b"where total_rating_count != null; "
                   b"sort total_rating_count desc; limit 1;")
    if isinstance(res, list) and res:
        print(f"  ✅ 成功　テスト取得: {res[0].get('name')}"
              f"（評価 {res[0].get('total_rating_count')} 件）")
    elif isinstance(res, dict) and "__error__" in res:
        print(f"  ❌ 失敗: {res['__error__'][:300]}")
        ok = False
    else:
        print(f"  ❌ 認証は通りましたが、データが返りませんでした: {str(res)[:200]}")
        ok = False
except SystemExit:
    raise
except Exception as e:
    print(f"  ❌ 失敗: {e}")
    ok = False

# ---- 3. データファイル ----------------------------------------------------
print("\n【3/3】同梱データを確認します …")
ch = DATA / "channels.tsv"
if not ch.exists():
    print("  ❌ data/channels.tsv が見つかりません。アップロード漏れの可能性があります。")
    ok = False
else:
    n = sum(1 for line in ch.read_text(encoding="utf-8").splitlines()[1:] if line.strip())
    print(f"  ✅ チャンネル候補 {n} 件を読み込めました")

for f in ("aliases.json", "blocklist.json"):
    if not (DATA / f).exists():
        print(f"  ❌ data/{f} が見つかりません。")
        ok = False
    else:
        print(f"  ✅ data/{f}")

print("\n" + "=" * 60)
if ok:
    print(" すべて成功しました。次のステップに進めます。")
    print(" Actions の『2. チャンネル情報を集める』を実行してください。")
else:
    print(" 失敗した項目があります。上の ❌ の行をそのまま報告してください。")
print("=" * 60)
sys.exit(0 if ok else 1)
