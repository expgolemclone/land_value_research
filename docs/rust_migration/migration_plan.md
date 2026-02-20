# Python → Rust 段階的移行計画

## Context

現在のパイプラインは全て Python で実装されており、3,618社の処理をシングルスレッドで逐次実行している。プロファイリングにより特定されたCPUボトルネックは以下の3つ:

1. **KDTree構築・探索** — `scipy.cKDTree` による ~3,000地価ポイントの空間探索
2. **IDW地価推定** — 逆距離加重補間の反復計算
3. **座標変換** — `pyproj.Transformer` (EPSG:4326→6677) と楕円体距離計算
4. **CSVインデックス構築** — `pandas` による大量住所CSVの読込・groupby

これらはすべて `landprice_tokyo.py` と `geocode_tokyo.py` に集中している。PyO3/maturin でこの2モジュールのみを Rust 拡張に置き換え、最小の実装コストで最大の高速化を得る。

---

## 移行スコープ

| 対象 | 移行する？ | 理由 |
|------|-----------|------|
| `landprice_tokyo.py` | **する** | CPU集約（KDTree, IDW, 座標変換）。全社処理で最も時間を消費 |
| `geocode_tokyo.py` | **する** | CPU集約（CSVインデックス構築、住所ルックアップ）。pandas依存を解消 |
| `jp_address.py` | **部分的** | geocode_tokyo が内部依存するため Rust 内部実装。Python公開は不要 |
| `anomaly.py` | しない | ルールベース判定。実行時間は無視できるレベル |
| `cache.py` | しない | JSON I/O。ディスクI/Oバウンドで Rust 化の効果なし |
| `company_config.py` | しない | YAML/CSV読込。起動時に1回のみ実行 |
| `utils.py` | しない | 24行のヘルパー。ボトルネックではない |
| `web_cache.py` | しない | ネットワークI/Oバウンド |
| `company_metadata_fallback.py` | しない | ネットワークI/Oバウンド |
| `pdf_extract.py` | しない | pdfplumber依存。Rust代替なし |
| `web_address_research.py` | しない | pdfplumber依存 + ネットワークI/O |
| `run.py` | しない | オーケストレータ。並列化は Python `multiprocessing` で対応可能 |
| `rank_market_cap_ratio.py` | しない | 集計・出力のみ。ボトルネックではない |

---

## 移行戦略: PyO3 拡張モジュール方式

既存 Python コードの中に Rust ワークスペースを配置し、`land_value_core` という Python 拡張モジュールとしてビルドする。各 Python モジュールは `try: from land_value_core import ... except ImportError: ...` のフォールバックパターンでラップし、Rust がビルドできない環境でも動作を保証する。

**注意:** `pyproject.toml` に maturin ビルド設定を追加し、`Cargo.toml` のワークスペースルートと共存させる必要がある（Phase 0 で設定）。

---

## ディレクトリ構造

```
land_value_research/
├── Cargo.toml                    # ワークスペースルート
├── rust/                         # Rust ソースツリー
│   ├── Cargo.toml                # land_value_core クレート
│   └── src/
│       ├── lib.rs                # #[pymodule] 定義
│       ├── types.rs              # 共通構造体 (PriceResult)
│       ├── jp_address.rs         # 住所正規化（内部使用のみ）
│       ├── geocode_tokyo.rs      # ジオコーダ
│       └── landprice_tokyo.rs    # IDW地価推定
├── src/                          # 既存Python（大部分はそのまま維持）
│   ├── landprice_tokyo.py        # → Rustラッパー化
│   ├── geocode_tokyo.py          # → Rustラッパー化
│   └── ...                       # その他は変更なし
└── tests/                        # 既存テスト（全フェーズで維持）
```

---

## Phase 0: 基盤構築

**作業内容:**
- [ ] `Cargo.toml`（ワークスペース）と `rust/Cargo.toml` を作成
- [ ] `rust/src/lib.rs` に最小限の `#[pymodule]` を定義（`rust_available()` 関数のみ）
- [ ] `rust/src/types.rs` に `PriceResult` を `#[pyclass(frozen)]` で定義
- [ ] `pyproject.toml` に maturin ビルド設定を追加（`Cargo.toml` ワークスペースルートとの共存を確認）
- [ ] `maturin develop --release` で Windows 上のビルドを検証
- [ ] CP932 CSV のデコードテスト（`encoding_rs` クレート）

**主要クレート:** `pyo3`

**検証:**
- [ ] `python -c "import land_value_core; print(land_value_core.rust_available())"`

---

## Phase 1: CPU集約モジュールの移行

**対象ファイル:**
- [ ] `src/landprice_tokyo.py` (151行) → `rust/src/landprice_tokyo.rs`
- [ ] `src/geocode_tokyo.py` (112行) → `rust/src/geocode_tokyo.rs`
- [ ] `src/jp_address.py` の内部関数を Rust 実装（geocode が依存するため。Python公開は不要）

### landprice_tokyo.rs

| Python (現在) | Rust (移行後) |
|--------------|--------------|
| `geopandas` GeoJSON読込 | `geojson` クレート |
| `scipy.cKDTree` | `kiddo` v4 (`KdTree<f64, 2>`) |
| `pyproj.Transformer` (EPSG:4326→6677) | `proj4rs` (純Rust、Cバインディング不要) |
| `pyproj.Geod.inv()` 楕円体距離 | `geographiclib-rs` クレート（Karney法、高精度） |
| `numpy` 配列演算 | `Vec<f64>` + イテレータ |

**削除可能なPython依存:** scipy, pyproj, geopandas, numpy, pandas

**PyO3インターフェース:**
```rust
#[pyclass]
struct LandPriceTokyo { /* KDTree, coords, prices, landuse_trees */ }

#[pymethods]
impl LandPriceTokyo {
    #[new]
    fn new(geojson_path: &str) -> PyResult<Self>;
    fn nearest(&self, lat: f64, lon: f64, landuse_kind: Option<String>) -> PyResult<PriceResult>;
    fn idw(&self, lat: f64, lon: f64, k: usize, p: f64, eps: f64, landuse_kind: Option<String>) -> PyResult<PriceResult>;
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

### Pythonラッパーパターン

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

**注意:** `kiddo` と `scipy.cKDTree` では同距離の点の返却順序が異なる可能性がある。IDW計算結果には大きな影響はないが、一致性テストでは同距離点の順序差に起因する微小な差異を許容すること。

---

## 並列化について

Phase 1 完了後、企業単位の並列処理が必要な場合は Python 側で `multiprocessing` を使い、各ワーカーで Rust 拡張を利用する。`run.py` の1,074行を Rust に移行するよりも遥かに低コストで並列化を実現できる。

```python
from multiprocessing import Pool

def process_company(target):
    # LandPriceTokyo, TokyoGeocoder は Rust 拡張（各プロセスで独立インスタンス）
    ...

with Pool(processes=4) as pool:
    results = pool.map(process_company, targets)
```

---

## リスクと緩和策

| リスク | 緩和策 |
|--------|--------|
| 浮動小数点精度差異（pyproj vs proj4rs） | `proj4rs` は PROJ の Rust ポートで精度差は最小。一致性テストで ±1円を検証 |
| Windows でのRustビルド | `proj4rs`, `kiddo` は純Rust、Cバインディング不要。Phase 0 で検証 |
| CP932 CSV エンコーディング | `encoding_rs::SHIFT_JIS.decode()` でUTF-8変換後にCSVパース |
| maturin の Python バージョン互換性 | CI で Python 3.10, 3.11, 3.12 のビルドを検証 |
| Rust コンパイル時間の増大 | `sccache` 導入、CI でのキャッシュ設定 |
| kiddo と cKDTree の同距離点順序差異 | IDW結果への影響は微小。一致性テストの許容幅で対応 |

---

## 検証方法

各フェーズ完了時:
- [ ] `cargo test` — Rust 単体テスト pass
- [ ] `maturin develop --release` — ビルド成功
- [ ] `python -m pytest tests/ -v` — 既存テスト全 pass
- [ ] `ruff check .` — Python リント pass
- [ ] `python run.py` で実データ処理を実行し、出力 CSV の差分確認
