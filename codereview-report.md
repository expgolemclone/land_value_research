# コードレビュー報告

## Findings

### 1. High: 既存 CSV の存在だけで「処理済み」と判定するため、壊れた出力や古い出力が永続化する

- `run.py:549-595` で無効化しているのは住所/地価オーバーライド変更だけです。
- `run.py:598-613` は `*_output.csv` が存在するだけで企業をスキップします。
- `run.py:1079-1084` は一時ファイルを使わず最終出力先を直接 `w` で開くため、途中終了すると 0 byte CSV が残ります。
- 実データにも `data/output/6501_output.csv`, `7425_output.csv`, `7575_output.csv`, `7596_output.csv`, `7615_output.csv`, `7619_output.csv`, `7980_output.csv` の 7 件の空ファイルが残っています。

この設計では、空ファイルも次回以降ずっと処理済み扱いになります。さらに、XBRL 原本、時価総額、地価 GeoJSON、ジオコード参照データ、CLI パラメータが変わっても既存 CSV は再計算されません。結果が静かに陳腐化するため、ランキング用途では高リスクです。

### 2. High: 地価点 ID が一意ではないのに `HashMap` のキーとして使っており、用途区分の参照が別地点へすり替わる

- `rust_src/landprice_tokyo.rs:78-126` で `L01_001/L01_002/L01_003` から `point_id` を作り、`point_idx_by_id.insert(...)` しています。
- `rust_src/landprice_tokyo.rs:196-207` はその ID から用途区分を引き直します。
- `run.py:912-927` はこの用途区分を `landuse_match` の基準用途や表示値に使っています。

現在の `data/landprice/merged/L01_L02_merged_13.geojson` には同一 `point_id` が 1,053 件あり、そのうち 435 件は用途区分が衝突しています。実例として `13101-000-002` は 2 点あり、座標 `139.73752,35.6812` の最近傍は単価 `2,530,000` 円の `2住居` ですが、`get_point_landuse_kind("13101-000-002")` は後勝ちで `1住居` を返します。

つまり、最近傍点そのものは正しく選ばれていても、その後の用途区分参照だけ別地点の値になります。`landuse_match` の再検索対象、出力 CSV の `最近傍用途区分`、監査時の公示点 ID が信用できなくなります。

### 3. Medium: `open_csv()` の CP932 フォールバックは実際には動作しない

- `src/utils.py:19-33` は `contextmanager` の中で `yield` 後に `UnicodeDecodeError` を捕まえ、次の encoding で再度 `yield` しようとしています。

CP932 ファイルを読むと、最初の `utf-8-sig` 読み込み中に例外が発生したあと `RuntimeError: generator didn't stop after throw()` になります。`open_csv()` の docstring は CP932 対応をうたっていますが、実装上その経路は使えません。入力 CSV やランキング集計元 CSV を CP932 で渡すと失敗します。

### 4. Medium: ジオコードキャッシュの依存ハッシュに `OAZA_CSV` が含まれていない

- `run.py:520-527` の `geocode_deps_hash` は `GAIKU_CSV` と `GEOCODE_RS` だけを使っています。
- しかし `rust_src/geocode_tokyo.rs:63-115` では `OAZA_CSV` から `oaza_first` と `muni_centroid` を構築しています。

そのため町丁目参照データだけを差し替えた場合、既存の `oaza_chome` / `muni_centroid` キャッシュは削除されません。低解像度住所の位置だけが古い値のまま残るため、参照データ更新後の再計算結果が混在します。

### 5. Medium: 不正な住所パッチをスキップしてもファイル自体は削除され、調査結果を失う

- `scripts/merge_address_patches.py:87-129` は、パッチ内の企業値が辞書でない場合に警告してスキップしますが、そのファイルを `merged_patch_files` に追加して最後に削除します。

再現例では `"'1234': broken"` のような不正パッチを渡すと、警告を出したうえで `merged_count=1`、元ファイル削除、`overrides.yaml` は空のままになります。自動調査で生成された手動補正データを、異常時に静かに失う経路です。

### 6. Low: 調査メモの Markdown リンクを無検証で HTML 化している

- `src/ranking_data.py:138-143` はリンク URL を HTML エスケープするだけで scheme を制限していません。
- `src/web.py:65-82` はその HTML を Web UI に渡します。

`[x](javascript:alert(1))` は `<a href="javascript:...">` として出力されます。メモはリポジトリ内ファイルですが、並列調査エージェントの生成物をそのまま公開 UI へ載せる設計なので、少なくとも `http/https` 以外を拒否する防御は必要です。

## Open Questions / Assumptions

- `skip_processed` は「途中再開の高速化」目的と理解しましたが、現状は成果物の妥当性検証や生成条件の署名がありません。意図が完全再計算回避なら、出力単位で依存ハッシュを持つ設計が必要です。
- 地価点 ID は公開データ由来の正式識別子ではなく、少なくともこのリポジトリ内では一意でない前提で扱う必要があります。
- `data/cache/` と既存 `data/output/` はレビュー対象外の派生成果物としましたが、空 CSV はコード不具合の現物証拠として確認しました。

## Verification

- `uv run pytest` -> 187 passed
- `cargo test` -> 38 passed
- `npx tsc --noEmit` -> success
- `uv run ruff check .` は NixOS の動的リンク制約で起動できず未実施

## Test Gaps

- 空 CSV / 不完全 CSV を `skip_processed` が再処理することを確認するテストがありません。
- 実データのような重複 `point_id` を含む地価 GeoJSON の回帰テストがありません。
- CP932 入力を `open_csv()` で読むテストがありません。
- `OAZA_CSV` 変更時にジオコードキャッシュを失効させるテストがありません。
- 不正なパッチファイルを保持するテストがありません。
- 調査メモの URL scheme 制限に関するテストがありません。
