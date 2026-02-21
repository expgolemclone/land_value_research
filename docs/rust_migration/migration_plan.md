# Python → Rust 段階的移行計画

- 目的は, 高速化である.

## Context

現在のパイプラインは全て Python で実装されており、3,618社の処理をシングルスレッドで逐次実行している。プロファイリングにより特定されたCPUボトルネックは以下の4つ:

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

## 呼び出し元の影響マップ

Rust 拡張が公開するクラス/型を import しているモジュール一覧。ラッパー化時に全箇所を確認する。

| 型/クラス | import 元 | 用途 |
|-----------|----------|------|
| `LandPriceTokyo` | `run.py:35` | `ctx.landprice` として保持、`.nearest()` / `.idw()` を呼び出し |
| `PriceResult` | `run.py:35`, `anomaly.py:7`, `tests/test_anomaly.py:9` | 戻り値型、フィールドアクセス、キャッシュからの再構築 |
| `TokyoGeocoder` | `run.py:34`, `tests/test_geocode_tokyo.py:6` | `ctx.geocoder` として保持、`.geocode()` を呼び出し |
| `normalize_addr` | `web_address_research.py:16` | Python から直接呼び出し（Rust非公開のため残す） |
| `split_tokyo_municipality` | `web_address_research.py:16` | Python から直接呼び出し（Rust非公開のため残す） |

**要注意:** `jp_address.py` の `normalize_addr` / `split_tokyo_municipality` は `web_address_research.py` が直接 import しているため、Python 側のファイルは削除せず維持する。Rust 実装は geocode_tokyo.rs 内部のみで使用。

---

## ディレクトリ構造

```
land_value_research/
├── Cargo.toml                    # ワークスペースルート
├── pyproject.toml                # [tool.maturin] セクション追加
├── rust/                         # Rust ソースツリー
│   ├── Cargo.toml                # land_value_core クレート (cdylib)
│   └── src/
│       ├── lib.rs                # #[pymodule] 定義 + rust_available()
│       ├── types.rs              # PriceResult (#[pyclass(frozen)])
│       ├── coord.rs              # 座標変換 (EPSG:4326→6677) + 楕円体距離
│       ├── jp_address.rs         # 住所正規化（Rust内部のみ、Python非公開）
│       ├── geocode_tokyo.rs      # TokyoGeocoder (#[pyclass])
│       └── landprice_tokyo.rs    # LandPriceTokyo (#[pyclass])
├── src/                          # 既存Python
│   ├── landprice_tokyo.py        # → Rustラッパー + Pythonフォールバック
│   ├── geocode_tokyo.py          # → Rustラッパー + Pythonフォールバック
│   ├── jp_address.py             # → 変更なし（web_address_research.py が依存）
│   └── ...                       # その他は変更なし
└── tests/
    ├── test_landprice_tokyo.py   # 変更不要（ラッパー経由で透過的に動作）
    ├── test_geocode_tokyo.py     # 変更不要
    ├── test_jp_address.py        # 変更不要（Python版を直接テスト）
    └── test_rust_parity.py       # 新規: Python/Rust一致性テスト
```

---

## Phase 0: 基盤構築

### Step 0-1: Rust ツールチェインの準備

- [x] `rustup` がインストールされていることを確認（`rustup --version`）
- [x] `maturin` を pip でインストール: `pip install maturin`
- [x] `requirements-dev.txt` に `maturin` を追加

### Step 0-2: Cargo ワークスペースの作成

- [x] プロジェクトルートに `Cargo.toml`（ワークスペースルート）を作成

```toml
# Cargo.toml (ワークスペースルート)
[workspace]
members = ["rust"]
resolver = "2"
```

- [x] `rust/` ディレクトリを作成
- [x] `rust/Cargo.toml` を作成

```toml
# rust/Cargo.toml
[package]
name = "land_value_core"
version = "0.1.0"
edition = "2021"

[lib]
name = "land_value_core"
crate-type = ["cdylib"]

[dependencies]
pyo3 = { version = "0.24", features = ["extension-module"] }
```

### Step 0-3: 最小限の PyO3 モジュール

- [x] `rust/src/lib.rs` を作成

```rust
use pyo3::prelude::*;

/// Rust 拡張が利用可能かどうかを返す
#[pyfunction]
fn rust_available() -> bool {
    true
}

/// land_value_core Python モジュール
#[pymodule]
fn land_value_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(rust_available, m)?)?;
    Ok(())
}
```

### Step 0-4: pyproject.toml へのビルド設定追加

- [x] 既存の `pyproject.toml` に maturin セクションを追加

```toml
# 既存セクションに追加
[build-system]
requires = ["maturin>=1.5,<2.0"]
build-backend = "maturin"

[tool.maturin]
manifest-path = "rust/Cargo.toml"
python-source = "."
module-name = "land_value_core"
features = ["pyo3/extension-module"]
```

**注意:** `python-source = "."` により、ビルド成果物がプロジェクトルートに配置され `import land_value_core` で直接読み込める。

### Step 0-5: ビルド検証

- [x] `maturin develop --release` を実行し、Windows 上でビルドが通ることを確認
- [x] `python -c "import land_value_core; print(land_value_core.rust_available())"` → `True`

### Step 0-6: types.rs — PriceResult の定義

- [x] `rust/src/types.rs` を作成

```rust
use pyo3::prelude::*;

/// Python の PriceResult dataclass と同等の構造体
#[pyclass(frozen, get_all)]
#[derive(Clone, Debug)]
pub struct PriceResult {
    pub unit_price: i64,
    pub nearest_id: String,
    pub nearest_dist_m: f64,
    pub knn_ids: Vec<String>,
    pub knn_dist_m: Vec<f64>,
    pub knn_prices: Vec<i64>,
}
```

**frozen + get_all の理由:** Python 側の `PriceResult` は `frozen=True` の dataclass。フィールドへのアトリビュートアクセス（`pr.unit_price`, `pr.nearest_id` 等）を `anomaly.py` と `run.py` が多用しているため、`get_all` で全フィールドを自動公開する。

- [x] `lib.rs` に `mod types;` を追加し、`m.add_class::<types::PriceResult>()?;` で登録
- [x] `maturin develop --release` → ビルド成功を確認

### Step 0-7: CP932 エンコーディングの検証

- [x] `rust/Cargo.toml` に `encoding_rs = "0.8"` を追加
- [x] geocode 用 CSV（`data/geocoding/geocode_ref_oaza_chome_tokyo_2024/13_2024.csv`）を CP932 として読み込み、UTF-8 にデコードできることを `#[test]` で検証

```rust
#[cfg(test)]
mod tests {
    use encoding_rs::SHIFT_JIS;
    use std::fs;

    #[test]
    fn test_cp932_decode() {
        // テスト用の小さな CP932 バイト列で検証
        let bytes = b"\x93\x8c\x8b\x9e\x93s"; // "東京都" in CP932
        let (decoded, _, had_errors) = SHIFT_JIS.decode(bytes);
        assert!(!had_errors);
        assert_eq!(decoded, "東京都");
    }
}
```

### Phase 0 完了条件

- [x] `maturin develop --release` が Windows 上で成功
- [x] `python -c "from land_value_core import rust_available, PriceResult; print(rust_available())"` → `True`
- [x] `cargo test` が pass
- [x] `python -m pytest tests/ -v` が全 pass（既存テストに影響なし）
- [x] `ruff check .` が pass

---

## Phase 1a: coord.rs — 座標変換・距離計算モジュール

`landprice_tokyo.rs` と `geocode_tokyo.rs` の両方が依存する座標系の基盤を先に実装する。Python 非公開の内部モジュール。

### 依存クレートの追加

```toml
# rust/Cargo.toml [dependencies] に追加
proj4rs = "0.1"
geographiclib-rs = "0.2"
```

### Step 1a-1: EPSG:4326 → EPSG:6677 座標変換

- [x] `coord.rs` を作成し `lonlat_to_plane()` を実装

Python 版の対応コード（`landprice_tokyo.py:39-41`）:

```python
self._transformer = Transformer.from_crs("EPSG:4326", "EPSG:6677", always_xy=True)
xs, ys = self._transformer.transform(self.lons, self.lats)
```

Rust 実装:

```rust
// rust/src/coord.rs
use proj4rs::Proj;

/// (lon, lat) → (x, y) in EPSG:6677 (JGD2011 / Japan Plane Rectangular IX)
pub fn lonlat_to_plane(lon: f64, lat: f64) -> (f64, f64) {
    let from = Proj::from_proj_string("+proj=longlat +datum=WGS84").unwrap();
    let to = Proj::from_proj_string(
        "+proj=tmerc +lat_0=36 +lon_0=139.833333333333 +k=0.9999 +x_0=0 +y_0=0 \
         +ellps=GRS80 +units=m +no_defs"
    ).unwrap();
    let mut point = (lon.to_radians(), lat.to_radians(), 0.0);
    proj4rs::transform::transform(&from, &to, &mut point).unwrap();
    (point.0, point.1)
}
```

**注意:** `proj4rs` は PROJ4 文字列で CRS を指定する。EPSG:6677 (Japan Plane Rectangular IX — 東京都) の PROJ4 文字列は上記の通り。`always_xy=True` に対応するため、入力は `(lon, lat)` 順とする。

- [x] `proj4rs` の PROJ4 文字列がpyproj の EPSG:6677 と同一結果を出すことを単体テストで検証（東京駅 (35.6812, 139.7671) を変換して pyproj の出力と比較、許容誤差 ±0.01m）

### Step 1a-2: WGS84 楕円体距離

Python 版の対応コード（`landprice_tokyo.py:75-81`）:

```python
self.geod = Geod(ellps="WGS84")
_, _, dist = self.geod.inv(lons1, lats1, lons2, lats2)
```

Rust 実装:

```rust
use geographiclib_rs::{Geodesic, InverseGeodesic};

/// WGS84 楕円体上の2点間距離 (m)
pub fn ellipsoid_distance(lat1: f64, lon1: f64, lat2: f64, lon2: f64) -> f64 {
    let geod = Geodesic::wgs84();
    let (s12, _, _) = geod.inverse(lat1, lon1, lat2, lon2);
    s12
}
```

- [x] 既知の2点間距離（国土地理院の検算値）と比較し ±0.001m 以内であることを `#[test]` で検証

### Step 1a-3: バッチ距離計算

```rust
/// 1点 (lat, lon) から複数点への楕円体距離を一括計算
pub fn ellipsoid_distances(
    lat: f64, lon: f64,
    target_lats: &[f64], target_lons: &[f64],
) -> Vec<f64> {
    let geod = Geodesic::wgs84();
    target_lats.iter().zip(target_lons.iter())
        .map(|(&t_lat, &t_lon)| {
            let (s12, _, _) = geod.inverse(lat, lon, t_lat, t_lon);
            s12
        })
        .collect()
}
```

### Phase 1a 完了条件

- [x] `cargo test` で coord モジュールの全テスト pass
- [x] pyproj との座標変換結果の差異が ±0.01m 以内
- [x] 楕円体距離の差異が ±0.001m 以内

---

## Phase 1b: landprice_tokyo.rs — IDW地価推定

### 依存クレートの追加

```toml
# rust/Cargo.toml [dependencies] に追加
kiddo = "4"
geojson = "0.24"
serde_json = "1"
serde = { version = "1", features = ["derive"] }
```

### Step 1b-1: GeoJSON 読込とデータ構造

Python 版の対応コード（`landprice_tokyo.py:22-53`）:

```rust
use std::collections::HashMap;
use std::fs;
use kiddo::KdTree;
use pyo3::prelude::*;

use crate::coord::{lonlat_to_plane, ellipsoid_distance, ellipsoid_distances};
use crate::types::PriceResult;

/// 地価ポイントの内部データ
struct LandPoint {
    lat: f64,
    lon: f64,
    plane_x: f64,
    plane_y: f64,
    price: f64,
    point_id: String,
    landuse_kind: String,
}

#[pyclass]
pub struct LandPriceTokyo {
    points: Vec<LandPoint>,
    point_idx_by_id: HashMap<String, usize>,
    tree_all: KdTree<f64, 2>,
    /// 用途区分別: (サブKdTree, グローバルインデックス配列)
    landuse_trees: HashMap<String, (KdTree<f64, 2>, Vec<usize>)>,
}
```

### Step 1b-2: コンストラクタ — GeoJSON パースと KDTree 構築

Python 版の対応コード（`landprice_tokyo.py:22-53`）:

```rust
#[pymethods]
impl LandPriceTokyo {
    #[new]
    fn new(geojson_path: &str) -> PyResult<Self> {
        let raw = fs::read_to_string(geojson_path)
            .map_err(|e| pyo3::exceptions::PyIOError::new_err(e.to_string()))?;
        let gj: geojson::FeatureCollection = serde_json::from_str(&raw)
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;

        let mut points = Vec::with_capacity(gj.features.len());
        let mut tree_all = KdTree::new();
        let mut point_idx_by_id = HashMap::new();

        for (i, feature) in gj.features.iter().enumerate() {
            let geom = feature.geometry.as_ref().unwrap();
            let coords = match &geom.value {
                geojson::Value::Point(c) => c.clone(),
                _ => continue,
            };
            let lon = coords[0];
            let lat = coords[1];

            let props = feature.properties.as_ref().unwrap();
            let l01_001 = props["L01_001"].as_str().unwrap_or("").to_string();
            let l01_002 = format!("{:0>3}", props["L01_002"].as_str().unwrap_or(""));
            let l01_003 = format!("{:0>3}", props["L01_003"].as_str().unwrap_or(""));
            let point_id = format!("{}-{}-{}", l01_001, l01_002, l01_003);

            let price: f64 = /* L01_008 を f64 にパース */;
            let landuse_kind = props.get("L01_051")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();

            let (px, py) = lonlat_to_plane(lon, lat);
            tree_all.add(&[px, py], i as u64);
            point_idx_by_id.insert(point_id.clone(), i);

            points.push(LandPoint {
                lat, lon, plane_x: px, plane_y: py,
                price, point_id, landuse_kind,
            });
        }

        // 用途区分別サブツリー構築
        let mut landuse_map: HashMap<String, Vec<usize>> = HashMap::new();
        for (i, pt) in points.iter().enumerate() {
            if !pt.landuse_kind.is_empty() {
                landuse_map.entry(pt.landuse_kind.clone())
                    .or_default()
                    .push(i);
            }
        }
        let mut landuse_trees = HashMap::new();
        for (kind, indices) in landuse_map {
            let mut sub_tree = KdTree::new();
            for (local_idx, &global_idx) in indices.iter().enumerate() {
                let pt = &points[global_idx];
                sub_tree.add(&[pt.plane_x, pt.plane_y], local_idx as u64);
            }
            landuse_trees.insert(kind, (sub_tree, indices));
        }

        Ok(Self { points, point_idx_by_id, tree_all, landuse_trees })
    }
}
```

**実装上の注意:**
- `L01_008`（地価）は GeoJSON 内で文字列 or 数値の場合がある。`as_f64()` と `as_str().parse::<f64>()` の両方を試す
- `L01_002`, `L01_003` は3桁ゼロ埋め（Python版: `str.zfill(3)`）
- `kiddo` v4 の `add()` は `(point, item)` 形式。`item` にグローバルインデックスを格納

### Step 1b-3: get_point_landuse_kind / get_landuse_kinds_for_ids

Python 版（`landprice_tokyo.py:55-62`）と1:1対応:

```rust
fn get_point_landuse_kind(&self, point_id: &str) -> String {
    match self.point_idx_by_id.get(point_id) {
        Some(&idx) => self.points[idx].landuse_kind.clone(),
        None => String::new(),
    }
}

fn get_landuse_kinds_for_ids(&self, point_ids: Vec<String>) -> Vec<String> {
    point_ids.iter().map(|pid| self.get_point_landuse_kind(pid)).collect()
}
```

### Step 1b-4: nearest() — 最近傍探索

Python 版（`landprice_tokyo.py:83-110`）の忠実な移植。タイブレーキングロジックを正確に再現する。

```rust
fn nearest(
    &self,
    lat: f64, lon: f64,
    landuse_kind: Option<String>,
) -> PyResult<PriceResult> {
    let (tree, global_idx) = self.get_tree_and_index(landuse_kind.as_deref());
    let (px, py) = lonlat_to_plane(lon, lat);
    let k_query = std::cmp::min(3, global_idx.len());

    // kiddo nearest_n は距離昇順で返す
    let neighbors = tree.nearest_n::<kiddo::SquaredEuclidean>(&[px, py], k_query);

    let cands_global: Vec<usize> = neighbors.iter()
        .map(|n| global_idx[n.item as usize])
        .collect();

    // 楕円体距離で正確に最近傍を決定
    let dists = self.ellipsoid_dists_for(lat, lon, &cands_global);
    let min_dist = dists.iter().cloned().fold(f64::INFINITY, f64::min);

    // 同距離タイの場合は point_id 辞書順で最小を選択
    let ties: Vec<usize> = dists.iter().enumerate()
        .filter(|(_, &d)| (d - min_dist).abs() < 1e-6)
        .map(|(i, _)| i)
        .collect();

    let best_idx = if ties.len() == 1 {
        cands_global[ties[0]]
    } else {
        ties.iter()
            .map(|&i| cands_global[i])
            .min_by_key(|&gi| &self.points[gi].point_id)
            .unwrap()
    };

    let dist_m = ellipsoid_distance(
        lat, lon,
        self.points[best_idx].lat, self.points[best_idx].lon,
    );

    Ok(PriceResult {
        unit_price: self.points[best_idx].price.round() as i64,
        nearest_id: self.points[best_idx].point_id.clone(),
        nearest_dist_m: dist_m,
        knn_ids: vec![self.points[best_idx].point_id.clone()],
        knn_dist_m: vec![dist_m],
        knn_prices: vec![self.points[best_idx].price.round() as i64],
    })
}
```

**タイブレーキング:** Python 版は `np.isclose(dists, min_dist)` でタイを判定し、`np.argmin(ids)` で point_id が辞書順最小の点を選択する。Rust 版も同一ロジックを再現。

### Step 1b-5: idw() — 逆距離加重補間

Python 版（`landprice_tokyo.py:112-150`）の忠実な移植:

```rust
fn idw(
    &self,
    lat: f64, lon: f64,
    k: usize, p: f64, eps: f64,
    landuse_kind: Option<String>,
) -> PyResult<PriceResult> {
    if k == 0 {
        return Err(pyo3::exceptions::PyValueError::new_err("kは1以上"));
    }

    let (tree, global_idx) = self.get_tree_and_index(landuse_kind.as_deref());
    let (px, py) = lonlat_to_plane(lon, lat);
    let k2 = std::cmp::min(k, global_idx.len());
    let k_query = std::cmp::min(k2 + 2, global_idx.len());

    let neighbors = tree.nearest_n::<kiddo::SquaredEuclidean>(&[px, py], k_query);
    let cands_global: Vec<usize> = neighbors.iter()
        .map(|n| global_idx[n.item as usize])
        .collect();

    // 楕円体距離を計算
    let dists = self.ellipsoid_dists_for(lat, lon, &cands_global);

    // 距離昇順 → point_id 辞書順でソートし上位 k2 件を選択
    let mut order: Vec<usize> = (0..cands_global.len()).collect();
    order.sort_by(|&a, &b| {
        dists[a].partial_cmp(&dists[b]).unwrap()
            .then_with(|| self.points[cands_global[a]].point_id
                .cmp(&self.points[cands_global[b]].point_id))
    });
    let selected: Vec<usize> = order.iter().take(k2).map(|&i| cands_global[i]).collect();
    let d = self.ellipsoid_dists_for(lat, lon, &selected);

    // IDW 加重平均: w_i = 1 / (d_i + eps)^p
    let weights: Vec<f64> = d.iter().map(|&di| 1.0 / (di + eps).powf(p)).collect();
    let w_sum: f64 = weights.iter().sum();
    let unit: f64 = weights.iter().zip(selected.iter())
        .map(|(&w, &gi)| w * self.points[gi].price)
        .sum::<f64>() / w_sum;

    let idx0 = selected[0];
    Ok(PriceResult {
        unit_price: unit.round() as i64,
        nearest_id: self.points[idx0].point_id.clone(),
        nearest_dist_m: d[0],
        knn_ids: selected.iter().map(|&gi| self.points[gi].point_id.clone()).collect(),
        knn_dist_m: d,
        knn_prices: selected.iter().map(|&gi| self.points[gi].price.round() as i64).collect(),
    })
}
```

### Step 1b-6: Rust 単体テスト

Python の `tests/test_landprice_tokyo.py` と同等のテストケースを `#[cfg(test)]` で実装:

```rust
#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use tempfile::NamedTempFile;

    fn make_test_geojson() -> NamedTempFile {
        let geojson = serde_json::json!({
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [139.77, 35.68]},
                    "properties": {
                        "L01_001": "13", "L01_002": "101", "L01_003": "001",
                        "L01_008": 1000000, "L01_051": "住宅"
                    }
                },
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [139.78, 35.69]},
                    "properties": {
                        "L01_001": "13", "L01_002": "101", "L01_003": "002",
                        "L01_008": 2000000, "L01_051": "商業"
                    }
                },
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [139.79, 35.70]},
                    "properties": {
                        "L01_001": "13", "L01_002": "101", "L01_003": "003",
                        "L01_008": 3000000, "L01_051": "商業"
                    }
                }
            ]
        });

        let mut f = NamedTempFile::new().unwrap();
        write!(f, "{}", geojson).unwrap();
        f
    }

    #[test]
    fn test_nearest_returns_closest_point() {
        let f = make_test_geojson();
        let lp = LandPriceTokyo::new(f.path().to_str().unwrap()).unwrap();
        let pr = lp.nearest(35.6801, 139.7701, None).unwrap();
        assert_eq!(pr.unit_price, 1000000);
        assert_eq!(pr.nearest_id, "13-101-001");
    }

    #[test]
    fn test_idw_returns_weighted_average() {
        let f = make_test_geojson();
        let lp = LandPriceTokyo::new(f.path().to_str().unwrap()).unwrap();
        let pr = lp.idw(35.685, 139.775, 2, 3.0, 1.0, None).unwrap();
        assert!(pr.unit_price > 1000000 && pr.unit_price < 2000000);
    }

    #[test]
    fn test_idw_k1_equals_nearest() {
        let f = make_test_geojson();
        let lp = LandPriceTokyo::new(f.path().to_str().unwrap()).unwrap();
        let pr_idw = lp.idw(35.6801, 139.7701, 1, 3.0, 1.0, None).unwrap();
        let pr_near = lp.nearest(35.6801, 139.7701, None).unwrap();
        assert_eq!(pr_idw.unit_price, pr_near.unit_price);
    }

    #[test]
    fn test_landuse_filter() {
        let f = make_test_geojson();
        let lp = LandPriceTokyo::new(f.path().to_str().unwrap()).unwrap();
        let pr = lp.nearest(35.68, 139.77, Some("商業".to_string())).unwrap();
        assert_eq!(lp.get_point_landuse_kind(&pr.nearest_id), "商業");
    }

    #[test]
    #[should_panic(expected = "kは1以上")]
    fn test_idw_invalid_k() {
        let f = make_test_geojson();
        let lp = LandPriceTokyo::new(f.path().to_str().unwrap()).unwrap();
        lp.idw(35.68, 139.77, 0, 3.0, 1.0, None).unwrap();
    }
}
```

### Phase 1b 完了条件

- [x] `cargo test` で landprice_tokyo モジュールの全テスト pass
- [x] `lib.rs` に `m.add_class::<landprice_tokyo::LandPriceTokyo>()?;` を追加
- [x] `maturin develop --release` → ビルド成功

---

## Phase 1c: jp_address.rs — 住所正規化（Rust 内部のみ）

`geocode_tokyo.rs` 内部で使用する住所正規化ロジック。Python 側には公開しない。

### 移植対象の関数

| Python 関数 | Rust 関数 | 行数 | 備考 |
|-------------|----------|------|------|
| `normalize_addr()` | `normalize_addr()` | 3行 | 全角→半角、漢数字→算用数字 |
| `num_to_kanji()` | `num_to_kanji()` | 10行 | 数値→漢字丁目名 |
| `_kanji_to_int()` | `kanji_to_int()` | 16行 | 漢数字→数値 |
| `_normalize_kanji_number_tokens()` | `normalize_kanji_number_tokens()` | 15行 | 正規表現による置換 |
| `split_tokyo_municipality()` | `split_tokyo_municipality()` | 5行 | 「東京都{区市町村}」の分割 |
| `parse_town_chome_block()` | `parse_town_chome_block()` | 40行 | 町名/丁目/街区の解析 |
| `build_oaza_chome_name()` | `build_oaza_chome_name()` | 1行 | 「{町名}{漢数字}丁目」の構築 |

### 依存クレートの追加

```toml
# rust/Cargo.toml [dependencies] に追加
regex = "1"
once_cell = "1"
```

### Step 1c-1: 全角→半角変換 + 正規化

```rust
// rust/src/jp_address.rs

use once_cell::sync::Lazy;
use regex::Regex;

/// 全角数字・ダッシュ等を半角に変換し、郵便番号記号・全角スペースを除去
pub fn normalize_addr(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for ch in s.trim().chars() {
        match ch {
            '０'..='９' => out.push((ch as u32 - '０' as u32 + b'0' as u32) as u8 as char),
            '－' | 'ー' | '―' | '−' => out.push('-'),
            '〒' | '\u{3000}' => {} // 除去
            _ => out.push(ch),
        }
    }
    normalize_kanji_number_tokens(&out)
}
```

### Step 1c-2: 漢数字⇔数値変換

```rust
const KANJI_DIGITS: &[(i32, &str)] = &[
    (0, "零"), (1, "一"), (2, "二"), (3, "三"), (4, "四"),
    (5, "五"), (6, "六"), (7, "七"), (8, "八"), (9, "九"), (10, "十"),
];

pub fn num_to_kanji(n: i32) -> Result<String, String> {
    if !(0..=99).contains(&n) {
        return Err(format!("num_to_kanjiの範囲外です(0-99): {}", n));
    }
    if n <= 10 {
        return Ok(KANJI_DIGITS[n as usize].1.to_string());
    }
    if n < 20 {
        return Ok(format!("十{}", KANJI_DIGITS[(n - 10) as usize].1));
    }
    let tens = n / 10;
    let ones = n % 10;
    if ones == 0 {
        return Ok(format!("{}十", KANJI_DIGITS[tens as usize].1));
    }
    Ok(format!("{}十{}", KANJI_DIGITS[tens as usize].1, KANJI_DIGITS[ones as usize].1))
}

pub fn kanji_to_int(token: &str) -> Option<i32> {
    // Python の _kanji_to_int() と同一ロジック
    // 「十」の位置による分岐: "二十三" → 23
    // ...
}
```

### Step 1c-3: 住所パース関数

```rust
static RE_TOKYO: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"^東京都(?P<muni>.+?(?:区|市|町|村))(?P<rest>.*)$").unwrap()
});
static RE_CHOME: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?P<town>.+?)(?P<chome>\d+)丁目(?P<rest>.*)$").unwrap()
});
static RE_HYPHEN: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?P<town>.+?)(?P<chome>\d+)-(?P<block>\d+)(?:-(?P<go>\d+))?.*$").unwrap()
});
static RE_BLOCK_NO_CHOME: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?P<town>.+?)(?P<block>\d+)(?:番(?:地)?|号).*$").unwrap()
});

pub fn split_tokyo_municipality(addr: &str) -> (Option<String>, String) {
    let a = normalize_addr(addr);
    match RE_TOKYO.captures(&a) {
        Some(caps) => (
            Some(caps["muni"].to_string()),
            caps["rest"].to_string(),
        ),
        None => (None, a),
    }
}

/// 町名/丁目/街区の粗い推定
pub fn parse_town_chome_block(addr: &str) -> (Option<String>, Option<i32>, Option<i32>) {
    let a = normalize_addr(addr);
    let (_, rest) = split_tokyo_municipality(&a);
    let rest = rest.trim_start();

    // 1) N丁目パターン
    if let Some(caps) = RE_CHOME.captures(rest) {
        let town = caps["town"].to_string();
        let chome: i32 = caps["chome"].parse().unwrap();
        let after = &caps["rest"];
        let block = Regex::new(r"(\d{1,4})").unwrap()
            .captures(after)
            .map(|m| m[1].parse::<i32>().unwrap());
        return (Some(town), Some(chome), block);
    }

    // 2) ハイフン形式
    if let Some(caps) = RE_HYPHEN.captures(rest) {
        let town = caps["town"].to_string();
        let chome: i32 = caps["chome"].parse().unwrap();
        let block: i32 = caps["block"].parse().unwrap();
        return (Some(town), Some(chome), Some(block));
    }

    // 3) 丁目なし番地
    if let Some(caps) = RE_BLOCK_NO_CHOME.captures(rest) {
        let town = caps["town"].trim().to_string();
        let block: i32 = caps["block"].parse().unwrap();
        return (Some(town), None, Some(block));
    }

    // 4) 町名のみ
    if !rest.is_empty() && rest.chars().all(|c| !c.is_ascii_digit() && c != ',' && c != '，' && c != '、') {
        return (Some(rest.to_string()), None, None);
    }

    (None, None, None)
}

pub fn build_oaza_chome_name(town: &str, chome: i32) -> String {
    format!("{}{}丁目", town, num_to_kanji(chome).unwrap())
}
```

### Step 1c-4: Rust 単体テスト

Python の `tests/test_jp_address.py` から全テストケースを移植:

```rust
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_num_to_kanji() {
        assert_eq!(num_to_kanji(0).unwrap(), "零");
        assert_eq!(num_to_kanji(1).unwrap(), "一");
        assert_eq!(num_to_kanji(10).unwrap(), "十");
        assert_eq!(num_to_kanji(11).unwrap(), "十一");
        assert_eq!(num_to_kanji(20).unwrap(), "二十");
        assert_eq!(num_to_kanji(35).unwrap(), "三十五");
        assert_eq!(num_to_kanji(99).unwrap(), "九十九");
        assert!(num_to_kanji(100).is_err());
    }

    #[test]
    fn test_parse_town_chome_block_chome_with_block() {
        let (t, c, b) = parse_town_chome_block("東京都中央区日本橋1丁目15番3号");
        assert_eq!(t.as_deref(), Some("日本橋"));
        assert_eq!(c, Some(1));
        assert_eq!(b, Some(15));
    }

    #[test]
    fn test_parse_town_chome_block_hyphen() {
        let (t, c, b) = parse_town_chome_block("東京都港区六本木3-4-33");
        assert_eq!(t.as_deref(), Some("六本木"));
        assert_eq!(c, Some(3));
        assert_eq!(b, Some(4));
    }

    #[test]
    fn test_parse_town_chome_block_no_chome() {
        let (t, c, b) = parse_town_chome_block("東京都中央区日本橋兜町11番5号");
        assert_eq!(t.as_deref(), Some("日本橋兜町"));
        assert_eq!(c, None);
        assert_eq!(b, Some(11));
    }

    #[test]
    fn test_normalize_fullwidth() {
        let result = normalize_addr("東京都港区六本木３丁目");
        assert!(result.contains("3丁目"));
    }

    #[test]
    fn test_normalize_kanji_chome() {
        let result = normalize_addr("東京都港区六本木三丁目");
        assert!(result.contains("3丁目"));
    }

    #[test]
    fn test_split_tokyo_municipality() {
        let (muni, rest) = split_tokyo_municipality("東京都中央区日本橋");
        assert_eq!(muni.as_deref(), Some("中央区"));
        assert_eq!(rest, "日本橋");
    }
}
```

### Phase 1c 完了条件

- [x] `cargo test` で jp_address モジュールの全テスト pass
- [x] Python 版 `test_jp_address.py` の全テストケースに対応する Rust テストが存在する

---

## Phase 1d: geocode_tokyo.rs — ジオコーダ

### 依存クレートの追加

```toml
# rust/Cargo.toml [dependencies] に追加
encoding_rs = "0.8"
csv = "1"
```

### Step 1d-1: CSV 読込（CP932/UTF-8 両対応）

Python 版の対応コード（`geocode_tokyo.py:19-27`）:

```rust
use encoding_rs::SHIFT_JIS;
use std::fs;

/// CP932 → UTF-8 → CSV パースの順で試行
fn read_csv_any(path: &str) -> Result<Vec<HashMap<String, String>>, String> {
    let bytes = fs::read(path).map_err(|e| e.to_string())?;

    // CP932 (= Shift_JIS のスーパーセット) を試行
    let (decoded, _, had_errors) = SHIFT_JIS.decode(&bytes);
    let text = if had_errors {
        // UTF-8 で試行
        String::from_utf8(bytes.clone()).map_err(|e| e.to_string())?
    } else {
        decoded.into_owned()
    };

    let mut reader = csv::Reader::from_reader(text.as_bytes());
    let headers: Vec<String> = reader.headers()
        .map_err(|e| e.to_string())?
        .iter()
        .map(|s| s.to_string())
        .collect();

    let mut rows = Vec::new();
    for result in reader.records() {
        let record = result.map_err(|e| e.to_string())?;
        let mut map = HashMap::new();
        for (i, field) in record.iter().enumerate() {
            if i < headers.len() {
                map.insert(headers[i].clone(), field.to_string());
            }
        }
        rows.push(map);
    }
    Ok(rows)
}
```

### Step 1d-2: インデックス構築

Python 版の対応コード（`geocode_tokyo.py:29-54`）:

```rust
use std::collections::HashMap;
use pyo3::prelude::*;

use crate::jp_address::{
    normalize_addr, split_tokyo_municipality,
    parse_town_chome_block, build_oaza_chome_name,
};

#[pyclass]
pub struct TokyoGeocoder {
    /// (市区町村名, 大字町丁目名, 街区符号) → (緯度, 経度)
    gaiku_index: HashMap<(String, String, String), (f64, f64)>,
    /// (市区町村名, 大字町丁目名) → (緯度, 経度) — ソート後の最初の行
    oaza_first: HashMap<(String, String), (f64, f64)>,
    /// 市区町村名 → (平均緯度, 平均経度)
    muni_centroid: HashMap<String, (f64, f64)>,
}
```

インデックス構築ロジック:

```rust
#[pymethods]
impl TokyoGeocoder {
    #[new]
    fn new(oaza_csv: &str, gaiku_csv: &str) -> PyResult<Self> {
        let oaza_rows = read_csv_any(oaza_csv)
            .map_err(|e| pyo3::exceptions::PyIOError::new_err(e))?;
        let gaiku_rows = read_csv_any(gaiku_csv)
            .map_err(|e| pyo3::exceptions::PyIOError::new_err(e))?;

        // --- oaza_first: groupby(市区町村名, 大字町丁目名) → ソート後最初の行 ---
        // Python版: sort_values(by=["緯度","経度"], ascending=[True,True]).iloc[0]
        let mut oaza_groups: HashMap<(String, String), Vec<(f64, f64)>> = HashMap::new();
        for row in &oaza_rows {
            if row.get("都道府県名").map(|s| s.as_str()) != Some("東京都") {
                continue;
            }
            let muni = row["市区町村名"].clone();
            let oaza = row["大字町丁目名"].clone();
            let lat: f64 = row["緯度"].parse().unwrap_or(0.0);
            let lon: f64 = row["経度"].parse().unwrap_or(0.0);
            oaza_groups.entry((muni, oaza)).or_default().push((lat, lon));
        }
        let mut oaza_first = HashMap::new();
        for ((muni, oaza), mut coords) in oaza_groups {
            // 緯度昇順 → 経度昇順
            coords.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap()
                .then(a.1.partial_cmp(&b.1).unwrap()));
            oaza_first.insert((muni, oaza), coords[0]);
        }

        // --- muni_centroid: groupby(市区町村名) → 緯度経度の平均 ---
        let mut muni_sums: HashMap<String, (f64, f64, usize)> = HashMap::new();
        for row in &oaza_rows {
            if row.get("都道府県名").map(|s| s.as_str()) != Some("東京都") {
                continue;
            }
            let muni = row["市区町村名"].clone();
            let lat: f64 = row["緯度"].parse().unwrap_or(0.0);
            let lon: f64 = row["経度"].parse().unwrap_or(0.0);
            let entry = muni_sums.entry(muni).or_insert((0.0, 0.0, 0));
            entry.0 += lat;
            entry.1 += lon;
            entry.2 += 1;
        }
        let mut muni_centroid = HashMap::new();
        for (muni, (sum_lat, sum_lon, count)) in muni_sums {
            muni_centroid.insert(muni, (sum_lat / count as f64, sum_lon / count as f64));
        }

        // --- gaiku_index: groupby(市区町村名, 大字・丁目名, 街区符号・地番) ---
        // Python版: sort_values(by=["代表フラグ","住居表示フラグ","緯度","経度"],
        //                       ascending=[False,False,True,True]).iloc[0]
        let mut gaiku_groups: HashMap<(String, String, String), Vec<(i32, i32, f64, f64)>> =
            HashMap::new();
        for row in &gaiku_rows {
            if row.get("都道府県名").map(|s| s.as_str()) != Some("東京都") {
                continue;
            }
            let muni = row["市区町村名"].clone();
            let oaza = row["大字・丁目名"].clone();
            let block = row["街区符号・地番"].to_string();
            let rep_flag: i32 = row.get("代表フラグ")
                .and_then(|s| s.parse().ok()).unwrap_or(0);
            let addr_flag: i32 = row.get("住居表示フラグ")
                .and_then(|s| s.parse().ok()).unwrap_or(0);
            let lat: f64 = row["緯度"].parse().unwrap_or(0.0);
            let lon: f64 = row["経度"].parse().unwrap_or(0.0);
            gaiku_groups.entry((muni, oaza, block))
                .or_default()
                .push((rep_flag, addr_flag, lat, lon));
        }
        let mut gaiku_index = HashMap::new();
        for ((muni, oaza, block), mut entries) in gaiku_groups {
            // 代表フラグ降順 → 住居表示フラグ降順 → 緯度昇順 → 経度昇順
            entries.sort_by(|a, b| {
                b.0.cmp(&a.0)
                    .then(b.1.cmp(&a.1))
                    .then(a.2.partial_cmp(&b.2).unwrap())
                    .then(a.3.partial_cmp(&b.3).unwrap())
            });
            gaiku_index.insert((muni, oaza, block), (entries[0].2, entries[0].3));
        }

        Ok(Self { gaiku_index, oaza_first, muni_centroid })
    }
}
```

### Step 1d-3: geocode() — 3段フォールバック

Python 版（`geocode_tokyo.py:56-111`）の忠実な移植:

```rust
fn geocode(&self, address: &str) -> PyResult<(f64, f64, String)> {
    let addr = normalize_addr(address);
    let (muni_opt, _) = split_tokyo_municipality(&addr);
    let muni = muni_opt.ok_or_else(|| {
        pyo3::exceptions::PyValueError::new_err(
            format!("東京都住所として解釈できません: {}", address)
        )
    })?;

    let (town, chome, block) = parse_town_chome_block(&addr);
    let mut gaiku_candidates: Vec<(String, i32)> = Vec::new();
    let mut oaza_candidates: Vec<String> = Vec::new();

    if let Some(ref t) = town {
        if let Some(c) = chome {
            if (0..=99).contains(&c) {
                let oaza_chome = build_oaza_chome_name(t, c);
                oaza_candidates.push(oaza_chome.clone());
                if let Some(b) = block {
                    gaiku_candidates.push((oaza_chome, b));
                    gaiku_candidates.push((t.clone(), c));
                }
            }
            oaza_candidates.push(t.clone());
        } else {
            oaza_candidates.push(t.clone());
            if let Some(b) = block {
                gaiku_candidates.push((t.clone(), b));
            }
        }
    }

    // 順序を維持して重複除去
    gaiku_candidates.dedup();
    oaza_candidates.dedup();

    // 街区優先
    for (oaza_name, gaiku_block) in &gaiku_candidates {
        let key = (muni.clone(), oaza_name.clone(), gaiku_block.to_string());
        if let Some(&(lat, lon)) = self.gaiku_index.get(&key) {
            return Ok((lat, lon, "gaiku".to_string()));
        }
    }

    // 町丁目フォールバック
    for oaza_name in &oaza_candidates {
        let key = (muni.clone(), oaza_name.clone());
        if let Some(&(lat, lon)) = self.oaza_first.get(&key) {
            return Ok((lat, lon, "oaza_chome".to_string()));
        }
    }

    // 区市フォールバック
    if let Some(&(lat, lon)) = self.muni_centroid.get(&muni) {
        return Ok((lat, lon, "muni_centroid".to_string()));
    }

    Err(pyo3::exceptions::PyValueError::new_err(
        format!("住所参照データで解決できません: {}", address)
    ))
}
```

### Step 1d-4: Rust 単体テスト

Python の `tests/test_geocode_tokyo.py` の全テストケースを移植。テスト用 CSV を `tempfile` で生成:

```rust
#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use tempfile::TempDir;

    fn setup_test_csvs() -> (TempDir, String, String) {
        let dir = TempDir::new().unwrap();
        let oaza_path = dir.path().join("oaza.csv");
        let gaiku_path = dir.path().join("gaiku.csv");

        let mut f = fs::File::create(&oaza_path).unwrap();
        writeln!(f, "都道府県名,市区町村名,大字町丁目名,緯度,経度").unwrap();
        writeln!(f, "東京都,中央区,日本橋兜町,35.670001,139.770001").unwrap();
        writeln!(f, "東京都,港区,六本木三丁目,35.660001,139.730001").unwrap();

        let mut f = fs::File::create(&gaiku_path).unwrap();
        writeln!(f, "都道府県名,市区町村名,大字・丁目名,街区符号・地番,代表フラグ,住居表示フラグ,緯度,経度").unwrap();
        writeln!(f, "東京都,中央区,日本橋兜町,11,1,1,35.680001,139.780001").unwrap();
        writeln!(f, "東京都,港区,六本木三丁目,4,1,1,35.665001,139.735001").unwrap();

        (dir, oaza_path.to_str().unwrap().to_string(),
         gaiku_path.to_str().unwrap().to_string())
    }

    #[test]
    fn test_geocode_bango_without_chome() {
        let (_dir, oaza, gaiku) = setup_test_csvs();
        let gc = TokyoGeocoder::new(&oaza, &gaiku).unwrap();
        let (lat, lon, level) = gc.geocode("東京都中央区日本橋兜町11番5号").unwrap();
        assert_eq!(level, "gaiku");
        assert!((lat - 35.680001).abs() < 1e-5);
        assert!((lon - 139.780001).abs() < 1e-5);
    }

    #[test]
    fn test_geocode_town_only() {
        let (_dir, oaza, gaiku) = setup_test_csvs();
        let gc = TokyoGeocoder::new(&oaza, &gaiku).unwrap();
        let (lat, lon, level) = gc.geocode("東京都中央区日本橋兜町").unwrap();
        assert_eq!(level, "oaza_chome");
        assert!((lat - 35.670001).abs() < 1e-5);
    }

    #[test]
    fn test_geocode_chome_hyphen() {
        let (_dir, oaza, gaiku) = setup_test_csvs();
        let gc = TokyoGeocoder::new(&oaza, &gaiku).unwrap();
        let (_, _, level) = gc.geocode("東京都港区六本木3-4-33").unwrap();
        assert_eq!(level, "gaiku");
    }
}
```

### Phase 1d 完了条件

- [x] `cargo test` で geocode_tokyo モジュールの全テスト pass
- [x] `lib.rs` に `m.add_class::<geocode_tokyo::TokyoGeocoder>()?;` を追加
- [x] `maturin develop --release` → ビルド成功

---

## Phase 2: Python ラッパー化と統合

### Step 2-1: src/landprice_tokyo.py のラッパー化

```python
# src/landprice_tokyo.py
from __future__ import annotations

try:
    from land_value_core import LandPriceTokyo, PriceResult  # Rust実装
    _RUST_BACKEND = True
except ImportError:
    _RUST_BACKEND = False

if not _RUST_BACKEND:
    # === 既存 Python 実装（フォールバック） ===
    from dataclasses import dataclass

    import geopandas as gpd
    import numpy as np
    from pyproj import Geod, Transformer
    from scipy.spatial import cKDTree

    @dataclass(frozen=True)
    class PriceResult:
        unit_price: int
        nearest_id: str
        nearest_dist_m: float
        knn_ids: list[str]
        knn_dist_m: list[float]
        knn_prices: list[int]

    class LandPriceTokyo:
        # ... 既存実装をそのまま維持 ...
        pass
```

**重要ポイント:**
- `PriceResult` は `anomaly.py:7` と `run.py:35` と `tests/test_anomaly.py:9` が `from src.landprice_tokyo import PriceResult` している
- Rust 版 `PriceResult` は `#[pyclass(frozen, get_all)]` で定義されているため、`.unit_price` 等のアトリビュートアクセスは Python dataclass と同等に動作する
- `run.py:632-638` でキャッシュから `PriceResult` を手動構築しているコードは、Rust 版でもコンストラクタを公開する必要がある

### Step 2-2: PriceResult コンストラクタの追加（run.py のキャッシュ復元用）

`run.py:632-638` で以下のようにキャッシュからの復元を行っている:

```python
pr = PriceResult(
    unit_price=int(dp["unit_price"]),
    nearest_id=str(dp["nearest_id"]),
    nearest_dist_m=float(dp["nearest_dist_m"]),
    knn_ids=[str(x) for x in dp.get("knn_ids", [])],
    knn_dist_m=[float(x) for x in dp.get("knn_dist_m", [])],
    knn_prices=[int(x) for x in dp.get("knn_prices", [])],
)
```

Rust 側に `#[new]` コンストラクタを追加:

```rust
// rust/src/types.rs に追加
#[pymethods]
impl PriceResult {
    #[new]
    fn new(
        unit_price: i64,
        nearest_id: String,
        nearest_dist_m: f64,
        knn_ids: Vec<String>,
        knn_dist_m: Vec<f64>,
        knn_prices: Vec<i64>,
    ) -> Self {
        Self { unit_price, nearest_id, nearest_dist_m, knn_ids, knn_dist_m, knn_prices }
    }
}
```

### Step 2-3: src/geocode_tokyo.py のラッパー化

```python
# src/geocode_tokyo.py
from __future__ import annotations

try:
    from land_value_core import TokyoGeocoder  # Rust実装
    _RUST_BACKEND = True
except ImportError:
    _RUST_BACKEND = False

if not _RUST_BACKEND:
    # === 既存 Python 実装（フォールバック） ===
    import logging
    import pandas as pd
    from src.jp_address import (
        build_oaza_chome_name, normalize_addr,
        parse_town_chome_block, split_tokyo_municipality,
    )

    logger = logging.getLogger(__name__)

    class TokyoGeocoder:
        # ... 既存実装をそのまま維持 ...
        pass
```

**注意:** `jp_address.py` は変更しない。`web_address_research.py:16` が `from src.jp_address import normalize_addr, split_tokyo_municipality` しているため。

### Step 2-4: 統合テスト

- [x] `python -m pytest tests/ -v` — 全既存テストが pass（Rust ラッパー経由で実行される）
- [x] テスト内で `_RUST_BACKEND` が `True` であることを確認するアサーションを一時的に追加

### Step 2-5: Python/Rust 一致性テスト（新規）

`tests/test_rust_parity.py` を新規作成し、実データで Python 版と Rust 版の出力を比較:

```python
"""Python 実装と Rust 実装の出力一致性を検証するテスト.

Rust バックエンドが利用可能な場合のみ実行される.
実データ (GeoJSON, 住所CSV) がある環境でのみ意味のある結果を返す.
"""
import os
import unittest

# テスト用にPython実装を強制ロード
import importlib

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
GEOJSON = os.path.join(DATA_DIR, "landprice", "tokyo_2025", "L01-25_13.geojson")
OAZA_CSV = os.path.join(DATA_DIR, "geocoding", "geocode_ref_oaza_chome_tokyo_2024", "13_2024.csv")
GAIKU_CSV = os.path.join(DATA_DIR, "geocoding", "geocode_ref_gaiku_tokyo_2024", "13_2024.csv")


@unittest.skipUnless(os.path.exists(GEOJSON), "実データが必要")
class TestLandPriceParity(unittest.TestCase):
    """Python版とRust版のLandPriceTokyoの出力一致性."""

    TOLERANCE_PRICE = 1        # ±1円
    TOLERANCE_DIST = 0.1       # ±0.1m

    def test_idw_parity(self) -> None:
        """複数地点でIDW結果が許容誤差内に収まること."""
        # Python実装とRust実装の両方をロードして比較
        ...

    def test_nearest_parity(self) -> None:
        """複数地点でnearest結果が一致すること."""
        ...


@unittest.skipUnless(os.path.exists(OAZA_CSV), "実データが必要")
class TestGeocodeParity(unittest.TestCase):
    """Python版とRust版のTokyoGeocoderの出力一致性."""

    TEST_ADDRESSES = [
        "東京都千代田区丸の内1丁目9番1号",
        "東京都中央区日本橋兜町11番5号",
        "東京都港区六本木3-4-33",
        "東京都渋谷区神宮前",
    ]

    def test_geocode_parity(self) -> None:
        """全テスト住所で同一の (lat, lon, level) が返ること."""
        ...
```

### Phase 2 完了条件

- [x] `python -m pytest tests/ -v` — 全テスト pass
- [x] `ruff check .` — pass
- [x] Rust バックエンドが使用されていることの確認:
  ```python
  python -c "from src.landprice_tokyo import _RUST_BACKEND; print(_RUST_BACKEND)"
  # → True
  ```
- [ ] `python run.py` で実データ全社処理が正常完了
- [ ] 出力 CSV の Python 版との差分が許容範囲内（`unit_price` ±1円、距離 ±0.1m）

---

## Phase 3: ベンチマーク・最適化・クリーンアップ

### Step 3-1: ベンチマーク

実データでの処理時間を比較:

```python
import time

# Rust版
t0 = time.perf_counter()
lp_rust = LandPriceTokyo(geojson_path)
init_rust = time.perf_counter() - t0

# Python版 (フォールバック)
# ... 同様に計測 ...

# 3,618社の geocode + IDW を計測
```

計測対象:
- [x] GeoJSON ロード + KDTree 構築時間
- [x] CSV ロード + インデックス構築時間
- [x] 1社あたりの geocode + IDW 処理時間
- [x] 全社処理の合計時間

### Step 3-2: 最適化の検討

ベンチマーク結果に応じて:

| 最適化項目 | 手法 | 優先度 |
|-----------|------|--------|
| KDTree 探索 | `kiddo` の `nearest_n` はすでに最適化済み | 不要の可能性大 |
| 座標変換 | `proj4rs::Proj` のインスタンスをキャッシュ（`coord.rs` で `Lazy` 化） | 高 |
| 楕円体距離 | `Geodesic::wgs84()` を `Lazy` でキャッシュ | 高 |
| CSV パース | `HashMap` ルックアップは O(1)、構築時間のみ最適化余地 | 低 |
| メモリ使用量 | `String` → `Box<str>` / `Arc<str>` で point_id を共有 | 低 |

### Step 3-3: Python 依存パッケージの整理

Rust バックエンドが利用可能な場合に不要になるパッケージ:

| パッケージ | 用途 | 削除可能? |
|-----------|------|----------|
| `scipy` | `cKDTree` | **可能** — `landprice_tokyo.py` のみが使用 |
| `pyproj` | 座標変換 | **可能** — `landprice_tokyo.py` のみが使用 |
| `geopandas` | GeoJSON 読込 | **可能** — `landprice_tokyo.py` のみが使用 |
| `numpy` | 配列演算 | **可能** — `landprice_tokyo.py` のみが使用 |
| `pandas` | CSV 読込 | **不可** — `geocode_tokyo.py` (Rust化) 以外にも使われる可能性あり。要調査 |

**方針:** Rust バックエンドが確立するまでは `requirements.txt` から削除しない。Phase 3 の最終段階で、Rust ビルドが CI で安定して動くことを確認した後に、`requirements-rust.txt`（Rust版用の軽量依存リスト）を作成する。

### Step 3-4: .gitignore の更新

```gitignore
# Rust build artifacts
/target/
/rust/target/
*.so
*.pyd
*.dll
land_value_core/
```

### Phase 3 完了条件

- [x] ベンチマーク結果を `docs/rust_migration/benchmark.md` に記録
- [x] 最適化を適用し、再ベンチマークで改善を確認
- [ ] `python run.py` が全社処理で正常完了
- [ ] 出力 CSV が Python 版と許容誤差内で一致

---

## 並列化について

Phase 2 完了後、企業単位の並列処理が必要な場合は Python 側で `multiprocessing` を使い、各ワーカーで Rust 拡張を利用する。`run.py` の1,074行を Rust に移行するよりも遥かに低コストで並列化を実現できる。

```python
from multiprocessing import Pool

def process_company(target):
    # LandPriceTokyo, TokyoGeocoder は Rust 拡張（各プロセスで独立インスタンス）
    ...

with Pool(processes=4) as pool:
    results = pool.map(process_company, targets)
```

**注意:** `LandPriceTokyo` と `TokyoGeocoder` は `#[pyclass]` で `Send` が必要。PyO3 のデフォルトでは `Send` は自動実装されないため、`unsendable` を避けるか、`multiprocessing` で各プロセスが独立にインスタンスを作成する方式を取る。

---

## リスクと緩和策

| リスク | 影響度 | 発生確率 | 緩和策 |
|--------|--------|---------|--------|
| 浮動小数点精度差異（pyproj vs proj4rs） | 低 | 中 | `proj4rs` は PROJ の Rust ポートで精度差は最小。Phase 1a で ±0.01m を検証。一致性テストで ±1円を最終確認 |
| Windows でのRustビルド | 高 | 低 | `proj4rs`, `kiddo`, `geographiclib-rs` は全て純Rust。Cバインディング不要。Phase 0 で早期検証 |
| CP932 CSV エンコーディング | 中 | 低 | `encoding_rs::SHIFT_JIS.decode()` でUTF-8変換後にCSVパース。Phase 0 で実データ検証 |
| maturin の Python バージョン互換性 | 中 | 低 | CI で Python 3.10, 3.11, 3.12 のビルドを検証 |
| Rust コンパイル時間の増大 | 低 | 中 | `sccache` 導入、CI でのキャッシュ設定。依存クレートは全て軽量 |
| kiddo と cKDTree の同距離点順序差異 | 低 | 高 | IDW結果への影響は微小（eps=1.0 で平滑化済み）。タイブレーキングを point_id 辞書順で統一 |
| GeoJSON の L01_008 フィールドの型不一致 | 中 | 中 | 文字列・数値の両方に対応するパースロジックを実装 |
| PriceResult の互換性（dataclass vs pyclass） | 高 | 低 | `#[pyclass(frozen, get_all)]` + `#[new]` でPython dataclass と同等のインターフェースを提供。`run.py` のキャッシュ復元コードの互換性を Phase 2 で検証 |

---

## 依存クレート一覧

| クレート | バージョン | 用途 | 純Rust? |
|---------|-----------|------|---------|
| `pyo3` | 0.24 | Python バインディング | Yes |
| `kiddo` | 4 | KDTree (空間探索) | Yes |
| `proj4rs` | 0.1 | 座標変換 (EPSG:4326→6677) | Yes |
| `geographiclib-rs` | 0.2 | WGS84 楕円体距離 (Karney法) | Yes |
| `geojson` | 0.24 | GeoJSON パース | Yes |
| `serde` / `serde_json` | 1 | JSON シリアライズ | Yes |
| `encoding_rs` | 0.8 | CP932 → UTF-8 デコード | Yes |
| `csv` | 1 | CSV パース | Yes |
| `regex` | 1 | 住所パース用正規表現 | Yes |
| `once_cell` | 1 | 正規表現の遅延初期化 | Yes |

全クレートが純 Rust 実装であり、C コンパイラや外部ライブラリへの依存がない。Windows 環境でのビルドに問題は生じない。

---

## 検証チェックリスト

各フェーズ完了時に必ず実行:

- [x] `cargo test` — Rust 単体テスト pass
- [ ] `cargo clippy -- -D warnings` — Rust リント pass
- [x] `maturin develop --release` — ビルド成功
- [x] `python -m pytest tests/ -v` — 既存 Python テスト全 pass
- [x] `ruff check .` — Python リント pass
- [ ] `python run.py` で実データ処理を実行し、出力 CSV の差分確認

## フェーズ間の依存関係

```
Phase 0 (基盤構築)
  │
  ├── Phase 1a (coord.rs — 座標変換)
  │     │
  │     ├── Phase 1b (landprice_tokyo.rs)  ← coord.rs に依存
  │     │
  │     └── Phase 1c (jp_address.rs)  ← coord.rs に依存しない（並行可能）
  │           │
  │           └── Phase 1d (geocode_tokyo.rs)  ← jp_address.rs に依存
  │
  └── Phase 2 (Python ラッパー化)  ← Phase 1b + 1d 完了後
        │
        └── Phase 3 (ベンチマーク・最適化)
```

**並行実施可能:** Phase 1b と Phase 1c は互いに依存しないため、並行して実装できる。
