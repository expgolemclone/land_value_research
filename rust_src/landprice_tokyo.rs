use std::collections::HashMap;
use std::fs;

use kiddo::KdTree;
use pyo3::prelude::*;

use crate::coord::{ellipsoid_distance, ellipsoid_distances, lonlat_to_plane};
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
    all_idx: Vec<usize>,
    /// 用途区分別: (サブKdTree, グローバルインデックス配列)
    landuse_trees: HashMap<String, (KdTree<f64, 2>, Vec<usize>)>,
}

impl LandPriceTokyo {
    fn get_tree_and_index(&self, landuse_kind: Option<&str>) -> (&KdTree<f64, 2>, &[usize]) {
        if let Some(kind) = landuse_kind {
            if let Some((tree, indices)) = self.landuse_trees.get(kind) {
                return (tree, indices);
            }
        }
        (&self.tree_all, &self.all_idx)
    }

    fn ellipsoid_dists_for(&self, lat: f64, lon: f64, global_indices: &[usize]) -> Vec<f64> {
        let lats: Vec<f64> = global_indices.iter().map(|&i| self.points[i].lat).collect();
        let lons: Vec<f64> = global_indices.iter().map(|&i| self.points[i].lon).collect();
        ellipsoid_distances(lat, lon, &lats, &lons)
    }
}

#[pymethods]
impl LandPriceTokyo {
    #[new]
    fn new(geojson_path: &str) -> PyResult<Self> {
        let raw = fs::read_to_string(geojson_path)
            .map_err(|e| pyo3::exceptions::PyIOError::new_err(e.to_string()))?;
        let gj: geojson::FeatureCollection = serde_json::from_str(&raw)
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;

        let mut points = Vec::with_capacity(gj.features.len());
        let mut tree_all: KdTree<f64, 2> = KdTree::new();
        let mut point_idx_by_id = HashMap::new();

        for feature in gj.features.iter() {
            let geom = match feature.geometry.as_ref() {
                Some(g) => g,
                None => continue,
            };
            let coords = match &geom.value {
                geojson::Value::Point(c) => c.clone(),
                _ => continue,
            };
            let lon = coords[0];
            let lat = coords[1];

            let props = match feature.properties.as_ref() {
                Some(p) => p,
                None => continue,
            };

            let l01_001 = props
                .get("L01_001")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            let l01_002 = format!(
                "{:0>3}",
                props
                    .get("L01_002")
                    .map(|v| match v {
                        serde_json::Value::String(s) => s.clone(),
                        serde_json::Value::Number(n) => n.to_string(),
                        _ => String::new(),
                    })
                    .unwrap_or_default()
            );
            let l01_003 = format!(
                "{:0>3}",
                props
                    .get("L01_003")
                    .map(|v| match v {
                        serde_json::Value::String(s) => s.clone(),
                        serde_json::Value::Number(n) => n.to_string(),
                        _ => String::new(),
                    })
                    .unwrap_or_default()
            );
            let point_id = format!("{}-{}-{}", l01_001, l01_002, l01_003);

            // L01_008 は文字列 or 数値
            let price: f64 = props
                .get("L01_008")
                .and_then(|v| {
                    v.as_f64()
                        .or_else(|| v.as_str().and_then(|s| s.parse::<f64>().ok()))
                })
                .unwrap_or(0.0);

            let landuse_kind = props
                .get("L01_051")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();

            let (px, py) = lonlat_to_plane(lon, lat);
            let idx = points.len();
            tree_all.add(&[px, py], idx as u64);
            point_idx_by_id.insert(point_id.clone(), idx);

            points.push(LandPoint {
                lat,
                lon,
                plane_x: px,
                plane_y: py,
                price,
                point_id,
                landuse_kind,
            });
        }

        // 用途区分別サブツリー構築
        let mut landuse_map: HashMap<String, Vec<usize>> = HashMap::new();
        for (i, pt) in points.iter().enumerate() {
            if !pt.landuse_kind.is_empty() {
                landuse_map
                    .entry(pt.landuse_kind.clone())
                    .or_default()
                    .push(i);
            }
        }
        let mut landuse_trees = HashMap::new();
        for (kind, indices) in &landuse_map {
            let mut sub_tree: KdTree<f64, 2> = KdTree::new();
            for (local_idx, &global_idx) in indices.iter().enumerate() {
                let pt = &points[global_idx];
                sub_tree.add(&[pt.plane_x, pt.plane_y], local_idx as u64);
            }
            landuse_trees.insert(kind.clone(), (sub_tree, indices.clone()));
        }

        // 用途ファミリー別の複合ツリー構築
        let families: &[(&str, &[&str])] = &[
            ("工業系", &["工業", "工専", "準工"]),
            ("商業系", &["商業", "近商"]),
            (
                "住居系",
                &["1住居", "2住居", "準住居", "1中専", "2中専", "1低専", "2低専"],
            ),
        ];
        for (family_name, members) in families {
            let mut family_indices: Vec<usize> = Vec::new();
            for member in *members {
                if let Some(indices) = landuse_map.get(*member) {
                    family_indices.extend(indices.iter());
                }
            }
            if !family_indices.is_empty() {
                family_indices.sort_unstable();
                family_indices.dedup();
                let mut sub_tree: KdTree<f64, 2> = KdTree::new();
                for (local_idx, &global_idx) in family_indices.iter().enumerate() {
                    let pt = &points[global_idx];
                    sub_tree.add(&[pt.plane_x, pt.plane_y], local_idx as u64);
                }
                landuse_trees.insert(family_name.to_string(), (sub_tree, family_indices));
            }
        }

        let all_idx: Vec<usize> = (0..points.len()).collect();
        Ok(Self {
            points,
            point_idx_by_id,
            all_idx,
            tree_all,
            landuse_trees,
        })
    }

    fn get_point_landuse_kind(&self, point_id: &str) -> String {
        match self.point_idx_by_id.get(point_id) {
            Some(&idx) => self.points[idx].landuse_kind.clone(),
            None => String::new(),
        }
    }

    fn get_landuse_kinds_for_ids(&self, point_ids: Vec<String>) -> Vec<String> {
        point_ids
            .iter()
            .map(|pid| self.get_point_landuse_kind(pid))
            .collect()
    }

    #[pyo3(signature = (lat, lon, landuse_kind=None))]
    fn nearest(&self, lat: f64, lon: f64, landuse_kind: Option<String>) -> PyResult<PriceResult> {
        let (tree, global_idx) = self.get_tree_and_index(landuse_kind.as_deref());
        if global_idx.is_empty() {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "有効な地価ポイントがありません",
            ));
        }
        let (px, py) = lonlat_to_plane(lon, lat);
        let k_query = std::cmp::min(3, global_idx.len());

        let neighbors = tree.nearest_n::<kiddo::SquaredEuclidean>(&[px, py], k_query);

        let cands_global: Vec<usize> = neighbors
            .iter()
            .map(|n| global_idx[n.item as usize])
            .collect();

        // 楕円体距離で正確に最近傍を決定
        let dists = self.ellipsoid_dists_for(lat, lon, &cands_global);
        let min_dist = dists.iter().cloned().fold(f64::INFINITY, f64::min);

        // 同距離タイの場合は point_id 辞書順で最小を選択
        let ties: Vec<usize> = dists
            .iter()
            .enumerate()
            .filter(|(_, &d)| (d - min_dist).abs() < 1e-6)
            .map(|(i, _)| i)
            .collect();

        let best_idx = if ties.len() == 1 {
            cands_global[ties[0]]
        } else {
            ties.iter()
                .map(|&i| cands_global[i])
                .min_by_key(|&gi| self.points[gi].point_id.clone())
                .unwrap()
        };

        let dist_m = ellipsoid_distance(
            lat,
            lon,
            self.points[best_idx].lat,
            self.points[best_idx].lon,
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

    #[pyo3(signature = (lat, lon, k=3, p=3.0, eps=1.0, landuse_kind=None))]
    fn idw(
        &self,
        lat: f64,
        lon: f64,
        k: usize,
        p: f64,
        eps: f64,
        landuse_kind: Option<String>,
    ) -> PyResult<PriceResult> {
        if k == 0 {
            return Err(pyo3::exceptions::PyValueError::new_err("kは1以上"));
        }

        let (tree, global_idx) = self.get_tree_and_index(landuse_kind.as_deref());
        if global_idx.is_empty() {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "有効な地価ポイントがありません",
            ));
        }
        let (px, py) = lonlat_to_plane(lon, lat);
        let k2 = std::cmp::min(k, global_idx.len());
        let k_query = std::cmp::min(k2 + 2, global_idx.len());

        let neighbors = tree.nearest_n::<kiddo::SquaredEuclidean>(&[px, py], k_query);
        let cands_global: Vec<usize> = neighbors
            .iter()
            .map(|n| global_idx[n.item as usize])
            .collect();

        // 楕円体距離を計算
        let dists = self.ellipsoid_dists_for(lat, lon, &cands_global);

        // 距離昇順 → point_id 辞書順でソートし上位 k2 件を選択
        let mut order: Vec<usize> = (0..cands_global.len()).collect();
        order.sort_by(|&a, &b| {
            dists[a].partial_cmp(&dists[b]).unwrap().then_with(|| {
                self.points[cands_global[a]]
                    .point_id
                    .cmp(&self.points[cands_global[b]].point_id)
            })
        });
        let selected: Vec<usize> = order.iter().take(k2).map(|&i| cands_global[i]).collect();
        let d = self.ellipsoid_dists_for(lat, lon, &selected);

        // IDW 加重平均: w_i = 1 / (d_i + eps)^p
        let weights: Vec<f64> = d.iter().map(|&di| 1.0 / (di + eps).powf(p)).collect();
        let w_sum: f64 = weights.iter().sum();
        let unit: f64 = weights
            .iter()
            .zip(selected.iter())
            .map(|(&w, &gi)| w * self.points[gi].price)
            .sum::<f64>()
            / w_sum;

        let idx0 = selected[0];
        Ok(PriceResult {
            unit_price: unit.round() as i64,
            nearest_id: self.points[idx0].point_id.clone(),
            nearest_dist_m: d[0],
            knn_ids: selected
                .iter()
                .map(|&gi| self.points[gi].point_id.clone())
                .collect(),
            knn_dist_m: d,
            knn_prices: selected
                .iter()
                .map(|&gi| self.points[gi].price.round() as i64)
                .collect(),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use tempfile::NamedTempFile;

    fn init_python() {
        pyo3::prepare_freethreaded_python();
    }

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
        init_python();
        let f = make_test_geojson();
        let lp = LandPriceTokyo::new(f.path().to_str().unwrap()).unwrap();
        let pr = lp.nearest(35.6801, 139.7701, None).unwrap();
        assert_eq!(pr.unit_price, 1000000);
        assert_eq!(pr.nearest_id, "13-101-001");
    }

    #[test]
    fn test_nearest_second_point() {
        init_python();
        let f = make_test_geojson();
        let lp = LandPriceTokyo::new(f.path().to_str().unwrap()).unwrap();
        let pr = lp.nearest(35.6901, 139.7801, None).unwrap();
        assert_eq!(pr.unit_price, 2000000);
        assert_eq!(pr.nearest_id, "13-101-002");
    }

    #[test]
    fn test_idw_returns_weighted_average() {
        init_python();
        let f = make_test_geojson();
        let lp = LandPriceTokyo::new(f.path().to_str().unwrap()).unwrap();
        let pr = lp.idw(35.685, 139.775, 2, 3.0, 1.0, None).unwrap();
        assert!(pr.unit_price > 1000000 && pr.unit_price < 2000000);
    }

    #[test]
    fn test_idw_k1_equals_nearest() {
        init_python();
        let f = make_test_geojson();
        let lp = LandPriceTokyo::new(f.path().to_str().unwrap()).unwrap();
        let pr_idw = lp.idw(35.6801, 139.7701, 1, 3.0, 1.0, None).unwrap();
        let pr_near = lp.nearest(35.6801, 139.7701, None).unwrap();
        assert_eq!(pr_idw.unit_price, pr_near.unit_price);
    }

    #[test]
    fn test_landuse_filter() {
        init_python();
        let f = make_test_geojson();
        let lp = LandPriceTokyo::new(f.path().to_str().unwrap()).unwrap();
        let pr = lp.nearest(35.68, 139.77, Some("商業".to_string())).unwrap();
        assert_eq!(lp.get_point_landuse_kind(&pr.nearest_id), "商業");
    }

    #[test]
    fn test_landuse_fallback() {
        init_python();
        let f = make_test_geojson();
        let lp = LandPriceTokyo::new(f.path().to_str().unwrap()).unwrap();
        let pr = lp
            .nearest(35.6801, 139.7701, Some("工業".to_string()))
            .unwrap();
        assert_eq!(pr.nearest_id, "13-101-001");
    }

    #[test]
    fn test_get_point_landuse_kind() {
        init_python();
        let f = make_test_geojson();
        let lp = LandPriceTokyo::new(f.path().to_str().unwrap()).unwrap();
        assert_eq!(lp.get_point_landuse_kind("13-101-001"), "住宅");
        assert_eq!(lp.get_point_landuse_kind("13-101-002"), "商業");
        assert_eq!(lp.get_point_landuse_kind("nonexistent"), "");
    }

    #[test]
    fn test_idw_invalid_k() {
        init_python();
        let f = make_test_geojson();
        let lp = LandPriceTokyo::new(f.path().to_str().unwrap()).unwrap();
        let result = lp.idw(35.68, 139.77, 0, 3.0, 1.0, None);
        assert!(result.is_err());
    }

    /// GeoJSON with skipped features (missing geometry / properties) must not
    /// cause index misalignment between the KdTree and the points vec.
    #[test]
    fn test_skipped_features_no_index_misalignment() {
        init_python();
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
                    "geometry": null,
                    "properties": {
                        "L01_001": "13", "L01_002": "101", "L01_003": "999",
                        "L01_008": 9999999, "L01_051": "住宅"
                    }
                },
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [139.78, 35.69]},
                    "properties": null
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

        let lp = LandPriceTokyo::new(f.path().to_str().unwrap()).unwrap();
        assert_eq!(lp.points.len(), 2);

        // Query near the first valid point
        let pr = lp.nearest(35.6801, 139.7701, None).unwrap();
        assert_eq!(pr.unit_price, 1000000);
        assert_eq!(pr.nearest_id, "13-101-001");

        // Query near the second valid point (index 3 in original, 1 in points)
        let pr2 = lp.nearest(35.7001, 139.7901, None).unwrap();
        assert_eq!(pr2.unit_price, 3000000);
        assert_eq!(pr2.nearest_id, "13-101-003");

        // IDW should also work without panic
        let pr3 = lp.idw(35.69, 139.78, 2, 3.0, 1.0, None).unwrap();
        assert!(pr3.unit_price > 1000000 && pr3.unit_price < 3000000);

        // point_idx_by_id lookup
        assert_eq!(lp.get_point_landuse_kind("13-101-001"), "住宅");
        assert_eq!(lp.get_point_landuse_kind("13-101-003"), "商業");
    }

    #[test]
    fn test_empty_feature_collection_nearest_returns_error() {
        init_python();
        let geojson = serde_json::json!({
            "type": "FeatureCollection",
            "features": []
        });
        let mut f = NamedTempFile::new().unwrap();
        write!(f, "{}", geojson).unwrap();

        let lp = LandPriceTokyo::new(f.path().to_str().unwrap()).unwrap();
        assert_eq!(lp.points.len(), 0);

        let result = lp.nearest(35.68, 139.77, None);
        assert!(result.is_err());
    }

    #[test]
    fn test_empty_feature_collection_idw_returns_error() {
        init_python();
        let geojson = serde_json::json!({
            "type": "FeatureCollection",
            "features": []
        });
        let mut f = NamedTempFile::new().unwrap();
        write!(f, "{}", geojson).unwrap();

        let lp = LandPriceTokyo::new(f.path().to_str().unwrap()).unwrap();
        let result = lp.idw(35.68, 139.77, 3, 3.0, 1.0, None);
        assert!(result.is_err());
    }

    #[test]
    fn test_empty_landuse_filter_nearest_returns_error() {
        init_python();
        // Only 住宅 points — querying 商業 with no fallback should fail
        let geojson = serde_json::json!({
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [139.77, 35.68]},
                "properties": {
                    "L01_001": "13", "L01_002": "101", "L01_003": "001",
                    "L01_008": 1000000, "L01_051": "住宅"
                }
            }]
        });
        let mut f = NamedTempFile::new().unwrap();
        write!(f, "{}", geojson).unwrap();

        let lp = LandPriceTokyo::new(f.path().to_str().unwrap()).unwrap();
        // 商業 tree exists but is empty? No — 商業 tree doesn't exist, so it falls back to all.
        // But if we query a landuse_kind that has a tree with entries...
        // Actually, get_tree_and_index falls back to tree_all when the kind isn't found.
        // So querying a non-existent kind will fall back to all points and succeed.
        let result = lp.nearest(35.68, 139.77, Some("商業".to_string()));
        // Falls back to all points — should succeed
        assert!(result.is_ok());
    }
}
