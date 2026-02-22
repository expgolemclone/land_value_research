# Code Review: 直近コミット (2026-02-22)

**レビュー観点:** 正しい住所を求められるか？

**対象コミット (6件, 新しい順):**

| # | Hash | Summary |
|---|------|---------|
| 1 | `5e5a2d5` | Fix Rust clippy warnings and apply cargo fmt |
| 2 | `51525b7` | Update .gitignore and CLAUDE.md for uv/unittest workflow |
| 3 | `4f93fed` | Wrap Hypothesis property tests in unittest.TestCase classes |
| 4 | `0bf0631` | Migrate dependencies to pyproject.toml and remove requirements*.txt |
| 5 | `9148996` | Add Rust toolchain and cargo config files |
| 6 | `922a1a9` | Stop excluding companies with critical anomalies from ranking |

---

## 総合評価

**住所精度への直接的な影響: 低〜中**

6件のコミットの大半はビルド環境・テスト基盤・コードスタイルの整備であり、住所解決ロジック自体を変更するものは少ない。ただし、Rustジオコーダの clippy 修正 (`5e5a2d5`) と、異常値企業を除外しなくなった変更 (`922a1a9`) は、住所精度の文脈で注意すべき点がある。

---

## 各コミットの詳細レビュー

### 1. `5e5a2d5` — Rust clippy warnings 修正 & cargo fmt

**変更内容:**
- `geocode_tokyo.rs`: 冗長クロージャの簡略化、`type GaikuKey` エイリアス導入
- `landprice_tokyo.rs`: フォーマット統一
- `Cargo.lock`: `indoc` クレート追加

**住所精度への影響: なし (安全)**

- ロジックの変更はゼロ。`map_err(|e| f(e))` → `map_err(f)` は動作同一。
- `GaikuKey` 型エイリアスは可読性向上のみで、ジオコーディング結果に影響しない。

**懸念点: なし**

---

### 2. `51525b7` — .gitignore / CLAUDE.md を uv/unittest に更新

**変更内容:**
- `.gitignore` に `.venv/` 追加
- CLAUDE.md のコマンド例を `uv run` / `unittest` ベースに更新

**住所精度への影響: なし**

- 開発ドキュメント変更のみ。

---

### 3. `4f93fed` — Hypothesis テストを unittest.TestCase にラップ

**変更内容:**
- `test_anomaly_props.py`, `test_jp_address_props.py`, `test_pdf_extract_props.py` の3ファイル
- トップレベル関数 → `TestCase` メソッドに変換
- `assert` → `self.assertEqual()` 等に置換

**住所精度への影響: 間接的にポジティブ**

- **`test_jp_address_props.py`** が `unittest discover` で確実に実行されるようになった。これは住所正規化ロジック (`jp_address.py`) の property-based テストであり、「東京都XX区...」のランダム住所文字列に対して正規化が破綻しないことを検証している。
- テストが CI から漏れていた場合、この修正により住所正規化のリグレッションを検出しやすくなる。

**懸念点:**
- `assert x == y` → `self.assertEqual(x, y)` の変換で、テストの意味が変わっていないか確認が必要。特に Hypothesis の `@given` デコレータと `TestCase` の組み合わせが正しく動作しているか。
  - **確認結果:** Hypothesis は `unittest.TestCase` を公式サポートしているため問題なし。

---

### 4. `0bf0631` — 依存管理を pyproject.toml に移行

**変更内容:**
- `requirements.txt` / `requirements-dev.txt` を削除
- `pyproject.toml` に `pdfplumber`, `pyyaml` を dependencies に追加
- dev group に `hypothesis`, `maturin`, `ruff` を追加

**住所精度への影響: 要確認**

- **`pandas`, `geopandas`, `numpy`, `pyproj`, `scipy` が除外されている。** コミットメッセージでは「コードベース内でインポートされていないため意図的に除外」とあるが、これらは元々 `requirements.txt` に含まれていた。
- 現在のコードでは Rust 拡張 (`land_value_core`) がジオコーディングと地価推定を担っているため、Python 側で `numpy`/`scipy`/`geopandas` を直接使っていない可能性が高い。

**懸念点:**
- **`pyproj` の除外は安全か？** もし座標変換 (EPSG:4326 → EPSG:6677) を Python 側でも行っている箇所があれば、実行時エラーになる。
  - → Rust 側 (`coord.rs`) で座標変換を実装しているため、Python 側では不要と思われるが、`import pyproj` がどこかに残っていないか grep で確認すべき。
- **`pdfplumber` のバージョン指定がない。** PDF テーブル抽出は住所取得の起点 (有価証券報告書からの施設一覧抽出) であり、`pdfplumber` のバージョンアップでテーブル検出精度が変わる可能性がある。バージョンピンが望ましい。

---

### 5. `9148996` — Rust toolchain / cargo config 追加

**変更内容:**
- `.cargo/config.toml`: `rust-lld.exe` リンカー指定
- `rust-toolchain.toml`: `stable` チャンネル固定

**住所精度への影響: なし**

- ビルド設定のみ。ジオコーダのロジックに影響なし。

---

### 6. `922a1a9` — Critical 異常企業をランキングから除外しない変更

**変更内容:**
- `run.py`: critical 異常時の早期 return を削除。全企業で「東京都合計」行を生成。
- `rank_market_cap_ratio.py`: 除外ロジック全削除 (~213行)。`load_excluded_rows()`, `write_excluded_markdown()` 等を削除。
- `scripts/open_excluded_related_files.ps1` を削除。
- テスト・ドキュメント更新。

**住所精度への影響: 中〜高 (最重要コミット)**

この変更は住所解決ロジック自体を変えていないが、**住所精度が低い企業もランキングに含まれるようになる**ため、最終出力の品質に直接影響する。

**具体的な影響シナリオ:**

1. **muni_centroid (市区町村代表点) で推定された大面積物件がランキングに残る**
   - 以前は critical 異常として除外されていた可能性がある
   - 補正係数 0.85 がかかるとはいえ、数km離れた代表点での地価推定は誤差が大きい
   - 例: 「東京都八王子市」の代表点と実際の物件所在地では地価が数倍異なりうる

2. **重複住所 (同一住所に複数物件) を持つ企業も含まれる**
   - `DUPLICATE_ADDRESS_CRITICAL_SITE_COUNT >= 2` で critical だったケースが、ランキングに反映される
   - 住所解決が不十分なために同じ低解像度住所が重複していた場合、地価が過大/過小評価される

3. **異常な単価 (2,000万円/m² 超 × 大面積) もランキングに残る**
   - これは住所精度というより地価推定精度の問題だが、根本原因が住所の誤解決である場合が多い

**リスク緩和策の確認:**
- critical 異常はログに記録される → ○ (ただし最終ランキングには反映)
- anomaly カラムに警告フラグが付く → ○ (CSV を見れば分かる)
- correction factor が適用される → ○ (muni_centroid で 0.85)

**推奨事項:**
- ランキング出力に「住所解像度」列を追加し、muni_centroid 企業を識別可能にすべき
- もしくは、ランキングに confidence score (high/medium/low) を表示して、利用者が判断できるようにすべき

---

## 住所精度パイプライン全体の評価

現在の3層フォールバック構造を踏まえた総合的な評価:

### 強み

| 項目 | 評価 |
|------|------|
| 3層フォールバック (override → web → report) | 適切な優先順位 |
| Web スクレイピングのスコアリング (5次元) | 多角的で合理的 |
| 集約名 ("本社他" 等) のフィルタリング | 誤マッチ防止に有効 |
| Rust ジオコーダの3段階フォールバック | gaiku → oaza → muni の順は妥当 |
| 補正係数による不確実性の反映 | 方向性は正しい |

### 今回のコミット群で生じた懸念

| # | 懸念事項 | 関連コミット | 重大度 |
|---|---------|-------------|--------|
| 1 | Critical 異常企業がランキングに含まれることで、住所精度の低い推定値が最終出力に混入 | `922a1a9` | **高** |
| 2 | `pdfplumber` バージョン未固定で、PDF テーブル抽出 (住所取得の起点) の安定性が保証されない | `0bf0631` | **中** |
| 3 | `pyproj` 等の除外が安全か未検証 (Python 側で座標変換を使う箇所が残っていないか) | `0bf0631` | **低** |
| 4 | Hypothesis テストの `TestCase` ラップが正しく動作しているか実行確認が必要 | `4f93fed` | **低** |

### 改善提案

1. **`922a1a9` の補完として、ランキング出力に住所解像度情報を付加する**
   - `geocode_level` (gaiku/oaza_chome/muni_centroid) と `confidence` (high/medium/low) を含めることで、利用者が低精度エントリを識別できるようにする

2. **`pdfplumber` のバージョンをピンする**
   - `pdfplumber>=0.10,<0.12` のように範囲指定し、メジャーバージョンアップによるテーブル検出変更を防ぐ

3. **Web スコアリング閾値 (40点) の妥当性を定期的に検証する**
   - 実際の address_overrides.yaml のエントリと web 解決結果を比較し、false positive / false negative 率を計測すべき

---

## 結論

直近6コミットは主にビルド環境・テスト基盤の近代化であり、住所解決ロジック自体への変更は含まれていない。しかし、**`922a1a9` (critical 異常企業の除外廃止)** は、住所精度の低いエントリが最終ランキングに含まれるようになるという重要な意味を持つ。

「正しい住所を求められるか？」という観点では、住所解決パイプライン (3層フォールバック + Rust ジオコーダ) の仕組み自体は健全だが、**低解像度の住所しか得られなかった場合の最終出力への影響が、今回の変更で拡大した**ことを認識すべきである。
