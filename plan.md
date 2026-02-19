# コードレビュー改善計画

コードレビューで発見された問題点を優先度順に整理し、修正タスクとして管理する。

## HIGH: 今すぐ修正すべき

- [x] **H1: `run.py` L756,914 — `unit_price_factor` が未使用**
  - `unit_price_factor = 1.0` が毎サイトループで初期化されるが、その後一度も更新されない
  - 出力の「地価単価補正係数」列が常に `1.000000` となり無意味
  - 対応案A: 変数を削除し、出力フィールドも削除する（破壊的変更）
  - 対応案B: `total_factor` を出力する（`geocode_factor` と統合されている現状を反映）
  - **判断**: 出力CSVの既存利用者への影響を考慮し、フィールドは残して `total_factor` を出力する

- [x] **H2: `company_metadata_fallback.py` L46-50 — `code` の入力バリデーション不足**
  - `fetch_from_irbank(code)` が `code` を直接URLに埋め込む: `f"https://irbank.net/{code}/ir"`
  - CSVから読み込んだ値がそのまま渡るため、不正な入力でURL injectionの可能性
  - 対応: `code` が4桁数字であることを検証し、不正ならば早期リターン

- [x] **H3: `company_metadata_fallback.py` L9 — `CompanyMetadata` が mutable**
  - `@lru_cache` でキャッシュされる値が mutable `dataclass` のため、外部から変更可能
  - 現状では読み取り専用で使われているが、将来的な事故防止のため `frozen=True` にする

## MEDIUM: 改善推奨

- [x] **M1: `rank_market_cap_ratio.py` L66-98 — YAMLパーサーの重複**
  - `rank_market_cap_ratio.py` が独自の正規表現YAMLパーサー `load_company_master()` を持つ
  - `src/company_config.py` には `yaml.safe_load` ベースの正規版がある
  - 対応: `rank_market_cap_ratio.py` を `src/company_config.py` の `load_company_master` に統一する
  - 注意: 型が `dict[str, dict[str, Any]]` vs `dict[str, dict[str, str]]` で異なるため調整が必要

- [x] **M2: `web_address_research.py` L284-288 — resolve_cache.json の毎回全書き込み**
  - `resolve()` メソッドが呼ばれるたびにキャッシュ全体をJSONへ書き出す
  - 対応: dirty flag を導入し、呼び出し元（`run.py`）から明示的に `flush()` する設計へ変更

- [x] **M3: `.gitignore` — キャッシュファイルの追加**
  - `data/cache/facilities_land/` (JSON) がgit管理対象になりうる
  - `data/cache/*.json` (price/geocode キャッシュ) も同様
  - `data/output/` も追加すべき
  - 対応: `.gitignore` に以下を追加
    ```
    data/cache/facilities_land/
    data/cache/*.json
    data/output/
    ```

- [x] **M4: `pdf_extract.py` L224-246 — 到達不能コード (dead code)**
  - ブロック `if land is None and land_col is None:` の中で `if land_col is not None` を再チェック
  - `land_col is None` が前提条件なので L226-227, L235-238 は到達不能
  - 対応: dead code を除去して可読性を改善

## LOW: 低優先度

- [x] **L1: `geocode_tokyo.py` L85-87 — 重複除去パターンの可読性**
  - `not (x in seen or seen.add(x))` パターンは `set.add()` が `None` を返すことに依存
  - 動作は正しいが初見で理解しづらい
  - 対応: `dict.fromkeys()` や明示的ループへの書き換え

- [x] **L2: `run.py` process_company (~400行) — 関数分割**
  - `process_company` 関数が約400行の巨大関数
  - サイトごとの処理ループ・duplicate検出・excluded行構築を個別関数に分離すると保守性向上
  - 対応: `_resolve_company_metadata`, `_process_site`, `_postprocess_duplicate_anomalies` に分割

- [x] **L3: `pdf_extract.py` L298-300 — 同名事業所の重複排除ロジック**
  - `dedup[x.site_name] = x` で最後の値が勝つ。同名の異なる拠点（例:「工場」が複数）でデータロスの可能性
  - 対応: `(site_name, location_short)` の複合キーで重複排除

- [x] **L4: `landprice_tokyo.py` — KD-Tree による高速化検討**
  - `_dist_all` が毎回全公示点との距離を計算（~数千点）
  - 現状のデータサイズでは問題ないが、scipy.spatial.cKDTree で高速化可能
  - 対応: 見送り（東京都限定で数千点のため現状十分高速、pyproj Geodの精度を維持）

- [x] **L5: `web_address_research.py` L175 — PDF判定がURL拡張子のみ**
  - `url.lower().endswith(".pdf")` でPDF判定。Content-Typeヘッダー未参照
  - リダイレクトやクエリ付きURLで誤判定の可能性
  - 対応: PDFマジックバイト(`%PDF-`)による判定を追加

## 実施方針

1. HIGH項目は即座に修正する（テストに影響しない安全な変更）
2. MEDIUM項目はHIGH完了後に順次対応
3. LOW項目は必要に応じて個別に実施
4. 各修正後にテスト実行で既存動作を確認: `python -m pytest tests/`
