# land_value_research

東京都内に保有土地を持つ上場企業について、有価証券報告書の設備情報、住所解決、地価参照データを組み合わせ、企業別の推定土地時価と時価総額比を算出するための調査パイプラインです。

## できること

- `config/input.csv` の証券コードを対象に企業別CSVを生成する
- 有価証券報告書PDFから主要設備の土地面積・簿価・所在地を抽出する
- 住所を東京都の街区・大字町丁目・自治体重心レベルへジオコードする
- 公示地価・基準地価データから土地単価を推定する
- 推定土地時価、含み益、評価倍率、時価総額比を算出する
- `data/ranking/ranking_market_cap_ratio.html` にランキングを出力する
- 住所・地価の手動補正を設定ファイルで管理する

## セットアップ

Python 3.13、Rust、`uv` が必要です。Nix が使える環境では次で開発シェルに入れます。

```bash
nix develop
```

依存関係は `pyproject.toml` と `uv.lock` で管理されています。`stock-db` は `../stock_db` の editable dependency として参照されます。

```bash
uv sync --dev
```

Rust 拡張は `maturin` 経由で Python モジュール `land_value_core` としてビルドされます。通常は `uv run` や `bin/land-value-run` 実行時に必要なビルドが行われます。

## 基本実行

通常実行:

```bash
bin/land-value-run
```

入力ファイルを指定する場合:

```bash
bin/land-value-run --input config/input.csv
```

自動再起動なしで直接 `run.py` を実行する場合:

```bash
uv run --no-build-isolation python run.py --no-auto-restart
```

主なオプション:

- `--output`: 企業別CSVの出力先。既定は `data/output`
- `--price-method`: 地価推定方法。`idw` または `nearest`
- `--k`: IDWで使う近傍点数。既定は `3`
- `--p`: IDWの距離減衰指数。既定は `3`
- `--allow-download` / `--no-allow-download`: PDF未存在時のダウンロード可否
- `--allow-web-address` / `--no-allow-web-address`: Web公開情報による住所補完の可否
- `--skip-processed` / `--no-skip-processed`: 既存の企業別CSVをスキップするか
- `--allow-auto-metadata` / `--no-allow-auto-metadata`: 会社名・PDF URL不足時の自動補完可否
- `--memory-limit`: メモリ使用率がこの値を超えたらキャッシュ保存後に終了。既定は `90`
- `--max-restarts`: メモリ制限終了時の最大再起動回数。既定は `10`

## 入力

既定の入力は `config/input.csv` です。ヘッダーなしの場合は、1列目を証券コード、2列目を任意の企業名として扱います。

ヘッダー付きの場合は以下の列を利用できます。

- `code` / `証券コード` / `コード`: 証券コード
- `company_name` / `銘柄名`: 企業名
- `securities_report_pdf_url`: 有価証券報告書PDF URL
- `market_cap`: 時価総額（円）
- `address_source_urls`: 住所調査で参照するURL。複数指定は `|` 区切り

時価総額は `input.csv` の `market_cap` を優先します。未指定の場合は `stock_db` の `stocks.shares_outstanding * prices.close` を使います。IRBank や Kabutan を時価総額の取得元としては使いません。

住所調査の source URL は実行時に `input.csv` の `address_source_urls` と `securities_report_pdf_url` から組み立てます。`company_metadata` には `address_source_urls` を保存しません。

## 出力

- `data/output/{証券コード}_output.csv`: 企業別の推定結果
- `data/output/run_logs/`: 実行ログ
- `data/ranking/ranking_market_cap_ratio.html`: 時価総額比ランキング
- `data/land.db`: 地価・ジオコード・PDF抽出・Web住所解決・企業メタデータなどの永続キャッシュ

企業別CSVの主な列:

- `証券コード`
- `企業名`
- `事業所名`
- `住所`
- `住所取得元`
- `住所取得元URL`
- `住所解決レベル`
- `土地面積(m2)`
- `地価単価(円/m2)`
- `推定土地時価(円)`
- `土地簿価(円)`
- `含み益(円)`
- `評価倍率`
- `時価総額(円)`
- `時価総額比`

ランキングHTMLは企業別CSVを集計して生成されます。単独で再生成する場合は次を実行します。

```bash
uv run python -m src.rank_market_cap_ratio
```

## 設定ファイル

### `config/address_overrides.yaml`

PDF抽出やWeb住所解決で不足・誤認しやすい住所を手動補正します。

文字列指定の場合は、事業所名に対する住所上書きです。

```yaml
'1234':
  本社: 東京都千代田区丸の内1丁目1番1号
```

リスト指定の場合は、有報上で合算された事業所を複数地点へ分割します。

```yaml
'1234':
  本社ほか:
    - name: 本社
      address: 東京都千代田区丸の内1丁目1番1号
      area_m2: 1000
      book_value_yen: 500000000
    - name: 倉庫
      address: 東京都大田区城南島2丁目6番1号
      area_m2: 3000
```

`book_value_yen` を省略した分割先は、残り簿価を面積比で按分します。`area_m2_is_estimated: true` を指定する場合は `area_m2_source` が必要です。

### `config/price_overrides.yaml`

地理的障壁や近傍点の偏りでIDW補間が不自然になる場合に、事業所別の地価単価を手動指定します。

```yaml
'1234':
  本社: 1200000
```

### `config/magic_numbers.toml`

異常値判定や信頼度評価などで使う閾値を管理します。

## データとキャッシュ

地価推定は `data/landprice/merged/L01_L02_merged_13.geojson` を使います。公示地価・基準地価のGeoJSONを統合する場合は次を実行します。

```bash
uv run python scripts/merge_landprice.py
```

住所解決は以下の東京都ジオコード参照データを使います。

- `data/geocoding/geocode_ref_gaiku_tokyo_2024/13_2024.csv`
- `data/geocoding/geocode_ref_oaza_chome_tokyo_2024/13_2024.csv`

主なキャッシュ:

- `data/cache/pdf/`: ダウンロード済み有報PDF
- `data/cache/web_address/`: Web住所調査のキャッシュ
- `data/land.db`: SQLiteキャッシュ

地価データやRustの地価・ジオコード実装が変わった場合、関連キャッシュは依存ハッシュにより無効化されます。`address_overrides.yaml` または `price_overrides.yaml` が変わった企業は、既存の企業別CSVが削除され再処理対象になります。

## 住所調査補助

ランキング上位の住所調査を並列実行する補助スクリプトがあります。

```bash
uv run python scripts/parallel_research.py split-address --n 3
uv run python scripts/parallel_research.py resolve-address --n 2
uv run python scripts/parallel_research.py split-address --n 3 --dry-run
```

`split-address` は合算住所の分割調査、`resolve-address` は低解像度住所の詳細化に使います。調査結果は `config/address_overrides.yaml` へ反映される想定です。

## 開発

テスト:

```bash
uv run pytest
```

Lint:

```bash
uv run ruff check .
```

Rust側のテスト:

```bash
cargo test
```

主な構成:

- `run.py`: メインパイプライン
- `src/schema.py`: CSV/ランキング列定義の単一ソース
- `src/company_store.py`: `land.db` 上の企業メタデータ入出力
- `src/stock_db_sync.py`: `stock.db` からの企業名・PDF URL・時価総額補完
- `src/pdf_extract.py`: 有報PDFからの設備情報抽出
- `src/geocode_tokyo.py`: 東京都住所ジオコード
- `src/landprice_tokyo.py`: 地価推定
- `src/rank_market_cap_ratio.py`: ランキングHTML生成
- `rust_src/`: 地価・ジオコードのRust実装
- `tests/`: Pythonテスト

設計上の詳細は `ARCHITECTURE.md` も参照してください。
