# 直近30分コミットレビュー（住所の正確性観点）

対象コミット（`git log --since '30 minutes ago'`、日時はコミットのタイムゾーン表記のまま）:

- `5e5a2d54017300023646da87e926a9de8798ff96` (2026-02-22T05:18:32+09:00) Fix Rust clippy warnings and apply cargo fmt
- `51525b7271507dc9d2e64ce61978ed46944aa2cb` (2026-02-22T05:18:21+09:00) Update .gitignore and CLAUDE.md for uv/unittest workflow
- `4f93fed5a330a45ad139a2e3da5c54a858e4740e` (2026-02-22T05:18:12+09:00) Wrap Hypothesis property tests in unittest.TestCase classes
- `0bf06319513f1c8abe238c0d7117bcec0e13aa5c` (2026-02-22T05:18:01+09:00) Migrate dependencies to pyproject.toml and remove requirements*.txt
- `91489968fa5257cd2a96d5b5400f57fa8edeb278` (2026-02-22T05:17:49+09:00) Add Rust toolchain and cargo config files
- `922a1a9ae60449c23c782f5f3dc9f6d7eab0c594` (2026-02-22T04:51:57+09:00) Stop excluding companies with critical anomalies from ranking

## 結論（「正しい住所を求められるか？」）

「正しい住所」を求めて改善していくこと自体は可能です（`住所解決レベル`、`住所取得元`、`異常値警告`、`anomaly_excluded_companies.csv` 等の“品質シグナル”が残っているため）。

ただし、今回の変更で **critical anomaly の企業もランキングに含める** 方針になったため、ランキングの利用者が「住所が粗い/誤っている可能性が高い会社」を結果表だけで見落としやすくなりました。住所精度を上げる運用（修正キュー作成、再解決のループ）を、従来の「除外」前提から「同梱して注意喚起」前提に寄せる必要があります。

## コミット別レビュー

### `922a1a9...` Stop excluding companies with critical anomalies from ranking

**住所精度への影響（大）**

- `run.py` が critical anomaly の企業でも `*_output.csv` を削除せず、東京都合計行も含めて出力するようになったため、「住所解決レベルが粗い/異常が出たケースを後から検証する材料」は増えました（住所改善の観点ではプラス）。
- 一方で `rank_market_cap_ratio.py` が除外企業を落とさずランキングに含めるようになったため、**住所が怪しい会社がランキングに混入する**のがデフォルトになります。
- ランキング側には `住所解決タグ`（`住所解決レベル` のユニーク集合）と `異常値警告` の集約が残っているのは良いですが、現状は「critical かどうか」を明示していません（`異常値警告` の文言次第で見落としうる）。

**提案（住所を“求める”運用に寄せる）**

- ランキング表に「critical anomaly 有無」または「critical 理由コード一覧（集約）」に相当する列を追加し、住所精度の低い結果を一目で識別できるようにする。
- `scripts/open_excluded_related_files.ps1` が削除された分、代替として「住所改善キュー」を作る（例: `住所解決レベル` が `muni_centroid/oaza_chome` を含む、または特定の異常理由コードを含む会社の一覧を生成して `address_overrides.yaml` の作業導線につなぐ）。

### `5e5a2d5...` Fix Rust clippy warnings and apply cargo fmt

**住所精度への影響（小〜注意点あり）**

- 変更は主に clippy 指摘の解消と整形で、住所→座標のロジックの意図は変わっていません。
- ただし `geocode_tokyo.rs` で緯度経度の parse 失敗時に `0.0` を採用する挙動は残っています（今回のコミットが導入したわけではないが、触ったタイミングなので注意点として記録）。`0.0,0.0` が混ざると centroid や街区代表点の選択を汚染し、誤った住所解決につながり得ます。

**提案**

- 参照CSVの緯度経度が欠損/不正な行は `skip` し、必要なら「スキップ件数」をログ/メトリクス化する（誤座標を混入させない）。

### `4f93fed...` Wrap Hypothesis property tests in unittest.TestCase classes

**住所精度への影響（中・改善）**

- `tests/test_jp_address_props.py` が `unittest` で `discover` 実行できる形に揃い、住所正規化や東京都区市町村の分割などの“壊れやすい前処理”が継続的に検証されやすくなりました。

**提案（テスト強化）**

- `split_tokyo_municipality` は「`muni` が None でない」だけでなく、`muni == 入力の muni` と `rest == 入力の残り` まで確認すると、誤判定（過剰マッチ）を抑えやすいです。
- `normalize_addr` は冪等性に加え、「表記ゆれ除去（全角/半角、スペース、ハイフン等）」の期待を具体例テストで固定すると、住所解決の再現性が上がります。

### `0bf0631...` Migrate dependencies to pyproject.toml and remove requirements*.txt

**住所精度への影響（間接・改善）**

- 住所の元データは PDF 由来の比率が高いので、`pdfplumber` が `pyproject.toml` の本体依存に入ったのは再現性の面でプラスです（環境差で抽出→住所精度が崩れる事故を減らす）。

### `9148996...` Add Rust toolchain and cargo config files

**住所精度への影響（間接・改善）**

- Rust ツールチェーン/リンカが固定され、`land_value_core`（ジオコーダ/地価推定）のビルド再現性が上がります。住所→座標→地価の一連の計算結果のブレを減らす方向です。

### `51525b7...` Update .gitignore and CLAUDE.md for uv/unittest workflow

**住所精度への影響（間接・改善）**

- `uv` と `unittest discover` の標準化で、住所関連テスト（`jp_address` の property テスト等）を回す導線が揃いました。結果として、住所正規化の退行が入りにくくなります。
