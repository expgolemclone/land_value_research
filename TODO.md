# todo

1. 設計上の改善提案

[x] (A) run.py が巨大すぎる（1262行）

メインの run.py に以下が混在しています:
異常値検出ロジック（detect_anomaly_warnings, detect_critical_anomaly, detect_duplicate_address_large_area）
CSV I/O（load_csv_rows, write_results）
キャッシュ管理（load_sites_cache, save_sites_cache, _atomic_json_write）
住所解決のグルーロジック

→ 異常値検出を src/anomaly.py に、キャッシュ管理を src/cache.py に分離済み。

[x] (B) dict[str, object] 型の多用 — run.py:926

出力行が dict[str, object] で、値が str | int | float の混在です。型安全性が低く、_postprocess_duplicate_anomalies 内で str(row.get(...))
のキャストが頻出しています。TypedDict か dataclass にすると堅牢になります。

→ OutputRow TypedDict を src/anomaly.py に導入済み。

[x] (C) detect_duplicate_address_large_area 内の辞書構造 — run.py:459-503

buckets の値が dict[str, object] で rows キーに list を入れるなど、構造体で表すべきものが dict のまま使われています。

→ _DuplicateBucket / DuplicateHit dataclass に変換済み。

---
3. エラーハンドリング

[x] (A) 全般的な except Exception: pass パターン

web_address_research.py:165, web_address_research.py:293
company_metadata_fallback.py:65, company_metadata_fallback.py:79

キャッシュ保存やフォールバック取得の失敗を黙殺しているのは意図的と思われますが、少なくとも logger.debug を入れると調査時に役立ちます。

→ logger.debug 追加済み。

[x] (B) run.py:1096 — サイト処理のエラーキャッチ

except (ValueError, KeyError) as e:
TypeError や IndexError がすり抜けます。PDF抽出後のデータ処理では予想外の型エラーが起きうるので、except Exception にして SITE_PROCESSING_ERROR
として記録するほうが安全です。

→ except Exception に拡大済み。

---
4. パフォーマンス

[x] (A) landprice_tokyo.py:54-62 — 毎回全点との距離計算

def _dist_all(self, lat: float, lon: float) -> np.ndarray:
IDW呼び出しのたびに全公示地価点（~3000点）との距離をGeod計算しています。k近傍のみ必要なので、scipy.spatial.cKDTree
で事前インデックスを構築すれば大幅に高速化できます。ただし楕円体距離との誤差は東京都内程度なら無視できるレベルです。

→ cKDTree (EPSG:6677平面座標) による空間インデックスを導入済み。楕円体距離は最終距離計算にのみ使用。

[x] (B) geocode_tokyo.py — pandas groupby でインデックス構築

初期化時に全データをメモリに辞書展開しているのは良い設計です。パフォーマンス上の問題はありません。

→ 問題なし。対応不要。

---
5. テストの網羅性

現在のテストは以下のみ:
test_geocode_tokyo.py — ジオコーダの4ケース
test_guardrails.py — 異常値検出の4ケース
test_company_config.py — 設定読み込みの7ケース

不足しているテスト:
[x] pdf_extract.py — 最も複雑なパース処理にテストがない（最優先） → tests/test_pdf_extract.py (34テスト)
[x] jp_address.py — num_to_kanji, parse_town_chome_block のエッジケース → tests/test_jp_address.py (19テスト)
[x] landprice_tokyo.py — IDW/nearest計算の正確性 → tests/test_landprice_tokyo.py (8テスト)
[x] web_address_research.py — スコアリングロジック → tests/test_web_address_research.py (6テスト)
[x] anomaly.py — 異常値検出 → tests/test_anomaly.py (20テスト)
[x] utils.py — SSRF保護 → tests/test_utils.py (10テスト)

---
6. セキュリティ

[x] (A) SSRF保護

urlopen を使用する箇所 (web_cache.py, company_metadata_fallback.py, web_address_research.py) で
ローカルホストやプライベートIPへのアクセスをブロックする保護を追加。

→ utils.py に validate_url_not_private() を追加し、全 urlopen 呼び出し前に検証済み。

[x] (B) sanitize_filename — 十分と記載。対応不要。

---
7. コードスタイル・その他

[x] utils.py の read_codes 関数は現在どこからも使われていない（デッドコード） → 削除済み。
[x] rank_market_cap_ratio.py:5 で subprocess をインポートし VS Code操作に使っていますが、PowerShellのSendKeysによるCtrl+T/Ctrl+Q送信は環境依存が強く不安定です → VS Code自動化コード (subprocess/shutil/SendKeys) 全削除済み。
[ ] run.py:29-42 の閾値定数群は、将来的にconfig化すると調整しやすくなります → src/anomaly.py に定数として分離済み。config化は将来課題。

---
優先度まとめ

┌────────┬────────────────────────────────────────────────────────────────────────┬────────┐
│ 優先度 │                                  項目                                  │ 状態   │
├────────┼────────────────────────────────────────────────────────────────────────┼────────┤
│ 高     │ pdf_extract.py のテスト追加                                            │ 完了   │
├────────┼────────────────────────────────────────────────────────────────────────┼────────┤
│ 高     │ run.py:875 の book_raw ゼロ判定を math.isclose に統一                  │ 完了   │
├────────┼────────────────────────────────────────────────────────────────────────┼────────┤
│ 中     │ company_metadata_fallback.py の doc_id 正規表現を S100[0-9A-Z]+ に修正 │ 完了   │
├────────┼────────────────────────────────────────────────────────────────────────┼────────┤
│ 中     │ サイト処理の except を Exception に拡大                                │ 完了   │
├────────┼────────────────────────────────────────────────────────────────────────┼────────┤
│ 中     │ run.py の巨大ファイルをモジュール分割                                  │ 完了   │
├────────┼────────────────────────────────────────────────────────────────────────┼────────┤
│ 低     │ utils.py:read_codes のデッドコード削除                                 │ 完了   │
├────────┼────────────────────────────────────────────────────────────────────────┼────────┤
│ 低     │ _dist_all のkd-tree最適化                                              │ 完了   │
├────────┼────────────────────────────────────────────────────────────────────────┼────────┤
│ 低     │ 各所の except Exception: pass に logger.debug 追加                     │ 完了   │
└────────┴────────────────────────────────────────────────────────────────────────┴────────┘
