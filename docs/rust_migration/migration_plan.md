# Python → Rust 段階的移行計画

## Context

現在のパイプラインは全て Python で実装されており、3,618社の処理をシングルスレッドで逐次実行している。CPU集約的な処理（KDTree探索、IDW地価推定、座標変換）と大量CSVのインデックス構築が主なボトルネック。PyO3/maturin を使った Python 拡張モジュールとして Rust を段階的に導入し、各フェーズで既存システムが動作する状態を維持する。

---

## 移行戦略: PyO3 拡張モジュール方式

既存 Python コードの中に Rust ワークスペースを配置し、`land_value_core` という Python 拡張モジュールとしてビルドする。各 Python モジュールは `try: from land_value_core import ... except ImportError: ...` のフォールバックパターンでラップし、Rust がビルドできない環境でも動作を保証する。

---

## ディレクトリ構造（最終形）

```
land_value_research/
├── Cargo.toml                    # ワークスペースルート
├── rust/                         # Rust ソースツリー
│   ├── Cargo.toml                # land_value_core クレート
│   └── src/
│       ├── lib.rs                # #[pymodule] 定義
│       ├── types.rs              # 共通構造体 (PriceResult, FacilityLand等)
│       ├── jp_address.rs         # 住所正規化
│       ├── anomaly.rs            # 異常値検出
│       ├── geocode_tokyo.rs      # ジオコーダ
│       ├── landprice_tokyo.rs    # IDW地価推定
│       ├── cache.rs              # JSONキャッシュI/O
│       ├── company_config.rs     # YAML/CSV設定読込
│       └── main.rs              # Phase 5: Rust CLIエントリポイント
├── src/                          # 既存Python（段階的にラッパー化）
│   ├── pdf_extract.py            # Pythonのまま維持（pdfplumber依存）
│   ├── web_address_research.py   # Pythonのまま維持（pdfplumber依存）
│   └── ...                       # 各モジュール → Rustラッパーへ
└── tests/                        # 既存テスト（全フェーズで維持）
```

---

## フェーズ一覧

| Phase | 対象 | 目的 | 削除可能なPython依存 |
|-------|------|------|---------------------|
| [ ] 0 | 基盤構築 | Rust環境・CI・最小動作確認 | なし |
| [ ] 1 | `landprice_tokyo.py`, `geocode_tokyo.py` | CPUボトルネック解消 | scipy, pyproj, geopandas, numpy, pandas |
| [ ] 2 | `jp_address.py`, `anomaly.py` | 純粋ロジックのRust化 | なし |
| [ ] 3 | `cache.py`, `company_config.py`, `utils.py` | I/Oユーティリティ移行 | PyYAML |
| [ ] 4 | `web_cache.py`, `company_metadata_fallback.py` | HTTP処理のRust化 | なし |
| [ ] 5 | `run.py`, `rank_market_cap_ratio.py` | オーケストレータのRust CLI化 + rayon並列化 | なし |

---

## Phase 0: 基盤構築

**作業内容:**
- [ ] `Cargo.toml`（ワークスペース）と `rust/Cargo.toml` を作成
- [ ] `rust/src/lib.rs` に最小限の `#[pymodule]` を定義（`rust_available()` 関数のみ）
- [ ] `rust/src/types.rs` に共通構造体 `PriceResult`, `FacilityLand` を `#[pyclass(frozen)]` で定義
- [ ] `pyproject.toml` に maturin ビルド設定を追加
- [ ] `maturin develop --release` で Windows 上のビルドを検証
- [ ] CP932 CSV のデコードテスト（`encoding_rs` クレート）

**主要クレート:** `pyo3`

**検証:**
- [ ] `python -c "import land_value_core; print(land_value_core.rust_available())"`

---

## Phase 1: CPU集約モジュールの移行（最重要）

**対象ファイル:**
- [ ] `src/landprice_tokyo.py` (151行) → `rust/src/landprice_tokyo.rs`
- [ ] `src/geocode_tokyo.py` (112行) → `rust/src/geocode_tokyo.rs`
- [ ] `src/jp_address.py` の内部関数も同時にRust実装（geocodeが依存するため）

### landprice_tokyo.rs

| Python (現在) | Rust (移行後) |
|--------------|--------------|
| `geopandas` GeoJSON読込 | `geojson` クレート |
| `scipy.cKDTree` | `kiddo` v4 (`KdTree<f64, 2>`) |
| `pyproj.Transformer` (EPSG:4326→6677) | `proj4rs` (純Rust、Cバインディング不要) |
| `pyproj.Geod.inv()` 楕円体距離 | `geodesic` クレートまたはVincenty自前実装 |
| `numpy` 配列演算 | `Vec<f64>` + イテレータ |

**PyO3インターフェース:**
```rust
#[pyclass]
struct LandPriceTokyo { /* KDTree, coords, prices, landuse_trees */ }

#[pymethods]
impl LandPriceTokyo {
    #[new]
    fn new(geojson_path: &str) -> PyResult<Self>;
    fn nearest(&self, lat: f64, lon: f64, landuse_kind: Option<&str>) -> PyResult<PriceResult>;
    fn idw(&self, lat: f64, lon: f64, k: usize, p: usize, eps: f64, landuse_kind: Option<&str>) -> PyResult<PriceResult>;
}
```

### geocode_tokyo.rs

| Python (現在) | Rust (移行後) |
|--------------|--------------|
| `pandas` CSV読込 + groupby | `encoding_rs` (CP932) + `csv` + `HashMap` |
| dict lookup 3段フォールバック | `HashMap` lookup |

**PyO3インターフェース:**
```rust
#[pyclass]
struct TokyoGeocoder { /* gaiku_index, oaza_first, muni_centroid */ }

#[pymethods]
impl TokyoGeocoder {
    #[new]
    fn new(oaza_csv: &str, gaiku_csv: &str) -> PyResult<Self>;
    fn geocode(&self, address: &str) -> PyResult<(f64, f64, String)>;
}
```

### Pythonラッパーパターン（全モジュール共通）

```python
try:
    from land_value_core import LandPriceTokyo, PriceResult
except ImportError:
    # 既存Python実装をフォールバック
    ...
```

### テスト戦略
- [ ] `cargo test` で Rust 単体テスト（既存テストケースを移植）
- [ ] `pytest tests/` が無変更で pass（ラッパー経由でRust実装が呼ばれる）
- [ ] 一致性テスト: Python実装とRust実装の結果比較（`unit_price` ±1円、距離 ±0.1m）

---

## Phase 2: 純粋ロジックモジュールの移行

**対象ファイル:**
- [ ] `src/jp_address.py` (179行) → `rust/src/jp_address.rs`（Phase 1で内部実装済み、Python公開を追加）
- [ ] `src/anomaly.py` (206行) → `rust/src/anomaly.rs`

### jp_address.rs
- [ ] 全角→半角変換テーブル: `match` 式
- [ ] 漢数字→整数変換: `match` 式
- [ ] 正規表現パース: `regex` クレート

### anomaly.rs
- [ ] 閾値定数 + ルールベース判定（外部依存なし）
- [ ] `detect_duplicate_address_large_area` は OutputRow (Python dict) を扱うためPhase 5まで Python に残す

---

## Phase 3: ユーティリティモジュールの移行

**対象ファイル:**
- [ ] `src/cache.py` (92行) → `rust/src/cache.rs`（`serde_json` + `tempfile`）
- [ ] `src/company_config.py` (46行) → `rust/src/company_config.rs`（`serde_yaml` + `csv`）
- [ ] `src/utils.py` (24行) → `rust/src/utils.rs`（`std::net::IpAddr`）

---

## Phase 4: HTTPモジュールの移行

**対象ファイル:**
- [ ] `src/web_cache.py` (31行) → `reqwest` (blocking)
- [ ] `src/company_metadata_fallback.py` (92行) → `reqwest` + `scraper`

**Pythonに残す:** `web_address_research.py`（pdfplumber依存）, `pdf_extract.py`（pdfplumber依存）

---

## Phase 5: オーケストレータの Rust CLI化

**対象ファイル:**
- [ ] `run.py` (1074行) → `rust/src/main.rs`（`clap` でCLI引数）
- [ ] `rank_market_cap_ratio.py` (416行) → `rust/src/ranking.rs`

**並列化:** `rayon` でPDF抽出以外の企業処理を並列化
```rust
targets.par_iter().map(|t| process_company(t, &ctx)).collect::<Vec<_>>();
```

**Python呼び出し:** PDF抽出は `Python::with_gil()` で Python を呼ぶ
```rust
pyo3::prepare_freethreaded_python();
Python::with_gil(|py| {
    let pdf_extract = py.import("src.pdf_extract")?;
    // ...
});
```

---

## リスクと緩和策

| リスク | 緩和策 |
|--------|--------|
| 浮動小数点精度差異（pyproj vs proj4rs） | `proj4rs` は PROJ の Rust ポートで精度差は最小。一致性テストで ±1円を検証 |
| Windows でのRustビルド | `proj4rs`, `kiddo` は純Rust、Cバインディング不要。Phase 0 で検証 |
| CP932 CSV エンコーディング | `encoding_rs::SHIFT_JIS.decode()` でUTF-8変換後にCSVパース |
| pdfplumber 代替不在 | `pdf_extract.py`, `web_address_research.py` は Python のまま維持。Phase 5 で Rust→Python 呼び出し |
| OutputRow (33列 TypedDict) の互換性 | Phase 1-4 は Python dict のまま。Phase 5 で Rust 構造体 + `serde(rename)` に移行 |
| GIL + rayon 並列化 | PDF抽出は逐次（GIL必要）、地価推定等は `py.allow_threads()` でGIL解放して並列化 |

---

## 検証方法

各フェーズ完了時:
- [ ] `cargo test` — Rust 単体テスト pass
- [ ] `maturin develop --release` — ビルド成功
- [ ] `python -m pytest tests/ -v` — 既存テスト全 pass
- [ ] `ruff check .` — Python リント pass
- [ ] `python run.py` で実データ処理を実行し、出力 CSV の差分確認
