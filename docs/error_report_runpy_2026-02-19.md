# run.py error report (2026-02-19)

## 目的

`run.py`を最後の企業まで実行する.
失敗原因や実行したことを全て, レポートにまとめる.

## rules
- 住所のweb補完(--allow-web-address)は必ず有効で実行する
- うまくいかなかった企業はmdに書いて, input.csvから除外して
- スクリプトは修正しない
- outputフォルダは修正しない
- yamlは修正して良い



## 実行環境

- OS: Windows (PowerShell)
- cwd: `C:\Users\0000250059\Desktop\stock\property\land_value_research`
- Python: 3.12.10
- command: `python run.py`
- timeout(外側): 30分

---

## 事象

処理中に `SystemExit` で停止した.

- 進捗表示: `[86/325] 開始: 4624 イサム塗料` の直後
- 停止理由: 有報PDF取得のタイムアウト
- エラーメッセージ(抜粋):
  - `証券コード4624の有報PDF取得に失敗しました.`
  - `The read operation timed out`

## 直接原因

`4624` の有報PDFをネットワーク経由で取得する処理が, 読み取りタイムアウトで失敗した.

参照していたURLは `config/company_master.yaml` の以下.

- `config/company_master.yaml`
  - `"4624".securities_report_pdf_url`
  - `https://disclosure2dl.edinet-fsa.go.jp/searchdocument/pdf/S100W7E9.pdf`

ダウンロード処理は `src/web_cache.py` の `urllib.request.urlopen(..., timeout=DEFAULT_TIMEOUT_SEC)` を使用しており, `DEFAULT_TIMEOUT_SEC = 20` になっている.

## 影響

- 途中停止したため, `write_results(...)` まで到達せず, 企業別の `*_output.csv` が今回の実行では出力されない可能性がある.
- 一方で, `data/cache` 配下のキャッシュ(PDF, 施設抽出結果, 地価/ジオコードキャッシュなど)は途中まで作られている可能性がある.

## 再現手順

1. `data/cache/pdf/4624_securities_report.pdf` が存在しない状態にする.
2. `python run.py` を実行する.
3. `4624` の段階でPDF取得がタイムアウトし, 上記メッセージで停止する.

## 対処案 (コード変更なし)

以下は, どれもコード修正なしで試せる.

1. PDFを手動で取得してキャッシュに配置する.
   - 保存先: `data/cache/pdf/4624_securities_report.pdf`
   - 例(タイムアウト長め): `Invoke-WebRequest -Uri "https://disclosure2dl.edinet-fsa.go.jp/searchdocument/pdf/S100W7E9.pdf" -OutFile "data/cache/pdf/4624_securities_report.pdf" -TimeoutSec 300`
2. `config/company_master.yaml` の `4624.securities_report_pdf_url` を, より安定して取得できるPDF直リンクに差し替える.
3. `--no-allow-download` にして, 事前に必要なPDFを `data/cache/pdf` に揃えてから実行する.

## 次のアクション案

- まずは 1 の手動ダウンロードで `data/cache/pdf/4624_securities_report.pdf` を作り, その後に `python run.py` を再実行する.

---
## 追記: 全上場ticker投入後の実行結果 (2026-02-19)

### 実施内容

- `config/input.csv` を JPX の内国株式4桁コードで再作成した.
- 件数: 3621件.
- 実行コマンド: `python run.py`

### 実行結果

- `run.py` は完走せず停止した.
- ログ上の総処理対象: 3312社 (`--skip-processed` により既存出力309件をスキップ).
- 停止時点ログ: `[37/3312] 開始: 1662 1662` の処理中.

### エラー詳細

- 例外種別: `KeyError: 92717`
- 発生箇所:
  - `src/jp_address.py` `num_to_kanji`
  - 呼び出し経路: `build_oaza_chome_name -> geocode_tokyo.geocode -> run.py _process_site`
- 失敗要因:
  - 丁目として想定外の巨大値 `92717` が渡され, 漢数字変換テーブルのキー範囲外アクセスが発生した.

### 補足

- これはPDF抽出値に異常な丁目数が混入したケースで再現した.
- 今回の依頼に従い, スクリプト本体(`run.py`や`src/*.py`)は編集していない.

## 追記: 失敗企業の除外対応 (2026-02-19)

### 対象企業

- 1662

### 除外理由

- `python run.py --allow-web-address` 実行時に, `[37/3312] 開始: 1662 1662` の処理中で停止した.
- 例外: `KeyError: 92717`
- 発生箇所: `src/jp_address.py` `num_to_kanji` (丁目値が想定外の巨大値)

### 実施した対応

- `config/input.csv` から `1662` の1行を削除した.
- スクリプト本体(`run.py`, `src/*.py`)と`data/output`は未変更.

## 追記: 失敗企業の除外対応2 (2026-02-19)

### 対象企業

- 2798

### 除外理由

- `python run.py --allow-web-address` 実行時に, `[389/3311] 開始: 2798 2798` の処理中で停止した.
- 例外: `ValueError` (住所解決不可)
- 発生箇所: `src/geocode_tokyo.py` `geocode`
- エラー末尾: `...解決できません: 東京都23区` (ログ文字化けあり)

### 実施した対応

- `config/input.csv` から `2798` の1行を削除した.
- スクリプト本体(`run.py`, `src/*.py`)と`data/output`は未変更.

## 追記: 失敗企業の除外対応3 (2026-02-19)

### 対象企業

- 3082

### 除外理由

- `python run.py --allow-web-address` 実行時に, `[492/3310] 開始: 3082 3082` の処理中で停止した.
- 例外: `ValueError` (住所解決不可)
- 発生箇所: `src/geocode_tokyo.py` `geocode`
- エラー末尾: `...解決できません: 東京都23区` (ログ文字化けあり)

### 実施した対応

- `config/input.csv` から `3082` の1行を削除した.
- スクリプト本体(`run.py`, `src/*.py`)と`data/output`は未変更.
