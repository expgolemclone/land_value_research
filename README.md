# land_value_research

東京都内に土地を持つ上場企業について、有価証券報告書PDFから設備・土地情報を抽出し、住所解決、地価推定、時価総額比ランキング生成までを行う調査用パイプラインです。

主な処理は以下です。

- 証券コード一覧から企業名・有報PDF URL・時価総額を取得または補完する
- 有報PDFの「設備の状況」から事業所名、所在地、土地面積、土地簿価を抽出する
- 東京都の街区・大字町丁目ジオコーディングデータで住所を緯度経度へ解決する
- 公示地価・基準地価データから土地単価を推定する
- 企業別CSVと時価総額比ランキングHTMLを出力する

## 必要環境

推奨環境は Nix dev shell です。

```bash
nix develop
```

dev shell には Python 3.13、Rust、uv、maturin、ruff、Node.js が含まれます。`pyproject.toml` は sibling リポジトリ `../stock_db` を editable 依存として参照するため、通常実行ではこのリポジトリと並べて `stock_db` が必要です。

## 入力データ

通常の入力ファイルは `config/input.csv` です。全銘柄向けには `config/input_full.csv` もあります。

1行1銘柄で1列目に証券コードを書きます。

```csv
1301
1514
1762
```

ヘッダー付きCSVも使えます。利用できる主な列は以下です。

| 列名                             | 内容                            |
| -------------------------------- | ------------------------------- | -------- |
| `code` / `証券コード` / `コード` | 証券コード                      |
| `company_name` / `銘柄名`        | 企業名                          |
| `securities_report_pdf_url`      | 有価証券報告書PDF URL           |
| `market_cap`                     | 時価総額（円）                  |
| `address_source_urls`            | 住所補完に使うURL。複数指定は ` | ` 区切り |

企業名、有報PDF URL、時価総額が入力にない場合、`land.db` や sibling の `stock_db` から補完します。時価総額が補完できない銘柄はスキップされます。

## 実行方法

### メインパイプライン

dev shell 内で実行します。

```bash
land-value-run --input config/input.csv
```

`--input` を省略すると `config/input.csv` を使います。

よく使うオプション:

| オプション                                           | 既定値        | 内容                                                       |
| ---------------------------------------------------- | ------------- | ---------------------------------------------------------- |
| `--output`                                           | `data/output` | 企業別CSVの出力先                                          |
| `--price-method`                                     | `idw`         | 地価推定方法。`idw` または `nearest`                       |
| `--k`                                                | `3`           | IDWで使う近傍点数                                          |
| `--p`                                                | `3`           | IDWの距離減衰指数                                          |
| `--allow-download` / `--no-allow-download`           | on            | PDF未取得時にダウンロードするか                            |
| `--allow-web-address` / `--no-allow-web-address`     | on            | Web公開情報で住所補完するか                                |
| `--skip-processed` / `--no-skip-processed`           | on            | 既存の `*_output.csv` がある銘柄をスキップするか           |
| `--allow-auto-metadata` / `--no-allow-auto-metadata` | on            | 不足メタデータをIRBANK等から補完するか                     |
| `--landuse-match` / `--no-landuse-match`             | on            | 用途区分を合わせて地価推定するか                           |
| `--memory-limit`                                     | `90`          | メモリ使用率がこの値を超えたら保存して終了する。`0` で無効 |
| `--no-auto-restart`                                  | off           | メモリ制限終了時の自動再起動を無効化する                   |

### 地価データのマージ

公示地価 L01 と基準地価 L02 のGeoJSONを統合する場合は以下を実行します。

```bash
uv run python scripts/merge_landprice.py
```

既定では `data/landprice/tokyo_2025/L01-25_13.geojson` と `data/landprice/chika_chousa_2024/L02-24_13.geojson` から `data/landprice/merged/L01_L02_merged_13.geojson` を生成します。

### ランキングHTMLの再生成

企業別CSVからランキングHTMLだけを再生成する場合は以下を実行します。

```bash
uv run python -m src.rank_market_cap_ratio --input-dir data/output --output data/ranking/ranking_market_cap_ratio.html
```

このHTMLはGitHub Pagesで以下から閲覧できます。

https://expgolemclone.github.io/land_value_research/data/ranking/ranking_market_cap_ratio.html

Pagesの配信元は `master` ブランチのリポジトリ直下です。公開用コピーは作らず、`data/ranking/ranking_market_cap_ratio.html` をそのまま配信します。

### 住所精度改善の補助調査

ランキング結果をもとに、合算住所の分割や低解像度住所の解決を並行実行できます。まずは `--dry-run` で対象を確認します。

```bash
uv run python scripts/parallel_research.py split-address --n 3 --dry-run
uv run python scripts/parallel_research.py resolve-address --n 2 --dry-run
```

実行時に生成された住所パッチは、メインパイプライン終了時に `config/address_overrides.yaml` へマージされます。

## 出力

| パス                                         | 内容                                                                |
| -------------------------------------------- | ------------------------------------------------------------------- |
| `data/output/*_output.csv`                   | 銘柄別の土地評価結果                                                |
| `data/ranking/ranking_market_cap_ratio.html` | 時価総額比ランキング                                                |
| `data/output/run_logs/`                      | 実行ログ                                                            |
| `data/cache/pdf/`                            | ダウンロード済み有報PDF                                             |
| `data/cache/web_address/`                    | Web住所調査のキャッシュ                                             |
| `data/land.db`                               | 企業メタデータ、PDF抽出、ジオコード、地価推定などのSQLiteキャッシュ |

企業別CSVの列定義は `src/schema.py` の `OUTPUT_COLUMNS` が正です。ランキングHTMLの列定義も同じファイルの `RANKING_COLUMNS` に集約されています。

## 設定ファイル

| パス                            | 内容                                         |
| ------------------------------- | -------------------------------------------- |
| `config/input.csv`              | 通常実行の対象銘柄                           |
| `config/input_full.csv`         | 全体実行向けの対象銘柄                       |
| `config/address_overrides.yaml` | 住所の手動補正、合算事業所の分割、面積の補正 |
| `config/price_overrides.yaml`   | 地価単価の手動補正                           |
| `config/magic_numbers.toml`     | ブラウザサービス等の実行パラメータ           |

## 開発・検証

テスト:

```bash
uv run pytest
```

Lint:

```bash
uv run ruff check .
```

Rust部分を含むため、Python拡張のビルドには maturin と Rust toolchain が必要です。Nix dev shell 内での実行を推奨します。
