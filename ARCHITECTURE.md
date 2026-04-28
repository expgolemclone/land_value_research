# Architecture

## Runtime

- `run.py`
  - メインの推定パイプライン
  - `land.db` に地価・ジオコード・有報拠点抽出・Web住所解決・override無効化ハッシュを保存する
  - `stocks.db` に企業名・有報PDF URL・住所探索元 URL・時価総額を保存する
- `src/rank_market_cap_ratio.py`
  - `data/output/*.csv` を集計し、ランキング HTML を生成する
  - 企業名の欠損補完は `stocks.db` を更新しながら行う
- `scripts/parallel_research.py`
  - ランキング上位の住所調査を並列実行する
  - 調査プロンプトには `land.db` 内の拠点抽出データと設備状況テキストを注入する

## Storage

- `data/land.db`
  - `land_price_cache`
  - `land_price_meta`
  - `geocode_cache`
  - `geocode_meta`
  - `facilities_land`
  - `web_address_resolve`
  - `invalidation_hashes`
- `stocks.db`
  - `stocks`
  - `market_caps`
  - 企業メタデータ関連テーブル

## Source Layout

- `src/browser.py`
  - `stock_db.browser_client.client` の薄い互換ラッパー
- `src/stealth.py`
  - `stock_db.proxy_pool` の再公開
- `src/company_store.py`
  - `stocks.db` の入出力集約
- `src/company_config.py`
  - `address_overrides.yaml` と `price_overrides.yaml` の読込
  - 分割住所ルールの展開
- `src/land_db/schema.py`
  - `land.db` の初期化と軽量マイグレーション
- `src/land_db/repo.py`
  - `land.db` の CRUD ヘルパー
- `src/web_address_research.py`
  - Web 調査結果を `land.db` の `web_address_resolve` に保存する

## Persistent Files

- `config/address_overrides.yaml`
  - 手動住所補正
- `config/price_overrides.yaml`
  - 手動地価補正
- `data/cache/pdf/`
  - ダウンロード済み有報 PDF
- `data/cache/web_address/`
  - Web 調査の生HTMLや派生解析ファイル
- `data/output/`
  - パイプライン出力 CSV
- `data/ranking/`
  - ランキング HTML

## Cache Rules

- 地価キャッシュ依存ハッシュ
  - `data/landprice/merged/*.geojson`
  - `rust_src/landprice_tokyo.rs`
- ジオコードキャッシュ依存ハッシュ
  - `data/geocoding/**/*.csv`
  - `rust_src/geocode_tokyo.rs`
- 拠点抽出データ
  - 有報 PDF の `size` と `mtime`
  - `cache_version`
- override 無効化
  - `address_overrides.yaml` と `price_overrides.yaml` の企業別 MD5
  - 差分が出た企業の `data/output/{code}_output.csv` を削除する

## Migration

- 旧構造化キャッシュからの移行は `scripts/migrate_to_land_db.py` を明示実行する
- 実行後の通常運用は `land.db` / `stocks.db` のみを正とし、旧 JSON/YAML キャッシュには戻さない

<!-- verified: 2026-04-28 -->
