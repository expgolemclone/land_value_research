use std::collections::HashMap;
use std::fs;

use encoding_rs::SHIFT_JIS;
use pyo3::prelude::*;

use crate::jp_address::{
    build_oaza_chome_name, normalize_addr, parse_town_chome_block, split_tokyo_municipality,
};

/// CP932 → UTF-8 → CSV パースの順で試行
fn read_csv_any(path: &str) -> Result<Vec<HashMap<String, String>>, String> {
    let bytes = fs::read(path).map_err(|e| e.to_string())?;

    // CP932 (= Shift_JIS のスーパーセット) を試行
    let (decoded, _, had_errors) = SHIFT_JIS.decode(&bytes);
    let text = if had_errors {
        // UTF-8 で試行
        String::from_utf8(bytes).map_err(|e| e.to_string())?
    } else {
        decoded.into_owned()
    };

    let mut reader = csv::Reader::from_reader(text.as_bytes());
    let headers: Vec<String> = reader
        .headers()
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

#[pyclass]
pub struct TokyoGeocoder {
    /// (市区町村名, 大字町丁目名, 街区符号) → (緯度, 経度)
    gaiku_index: HashMap<(String, String, String), (f64, f64)>,
    /// (市区町村名, 大字町丁目名) → (緯度, 経度) — ソート後の最初の行
    oaza_first: HashMap<(String, String), (f64, f64)>,
    /// 市区町村名 → (平均緯度, 平均経度)
    muni_centroid: HashMap<String, (f64, f64)>,
}

#[pymethods]
impl TokyoGeocoder {
    #[new]
    fn new(oaza_csv: &str, gaiku_csv: &str) -> PyResult<Self> {
        let oaza_rows = read_csv_any(oaza_csv).map_err(pyo3::exceptions::PyIOError::new_err)?;
        let gaiku_rows = read_csv_any(gaiku_csv).map_err(pyo3::exceptions::PyIOError::new_err)?;

        // --- oaza_first: groupby(市区町村名, 大字町丁目名) → ソート後最初の行 ---
        let mut oaza_groups: HashMap<(String, String), Vec<(f64, f64)>> = HashMap::new();
        for row in &oaza_rows {
            if row.get("都道府県名").map(|s| s.as_str()) != Some("東京都") {
                continue;
            }
            let muni = row.get("市区町村名").cloned().unwrap_or_default();
            let oaza =
                normalize_addr(&row.get("大字町丁目名").cloned().unwrap_or_default());
            let Some(lat) = row.get("緯度").and_then(|s| s.parse::<f64>().ok()) else {
                continue;
            };
            let Some(lon) = row.get("経度").and_then(|s| s.parse::<f64>().ok()) else {
                continue;
            };
            oaza_groups
                .entry((muni, oaza))
                .or_default()
                .push((lat, lon));
        }
        let mut oaza_first = HashMap::new();
        for ((muni, oaza), mut coords) in oaza_groups {
            // 緯度昇順 → 経度昇順
            coords.sort_by(|a, b| {
                a.0.partial_cmp(&b.0)
                    .unwrap()
                    .then(a.1.partial_cmp(&b.1).unwrap())
            });
            oaza_first.insert((muni, oaza), coords[0]);
        }

        // --- muni_centroid: groupby(市区町村名) → 緯度経度の平均 ---
        let mut muni_sums: HashMap<String, (f64, f64, usize)> = HashMap::new();
        for row in &oaza_rows {
            if row.get("都道府県名").map(|s| s.as_str()) != Some("東京都") {
                continue;
            }
            let muni = row.get("市区町村名").cloned().unwrap_or_default();
            let Some(lat) = row.get("緯度").and_then(|s| s.parse::<f64>().ok()) else {
                continue;
            };
            let Some(lon) = row.get("経度").and_then(|s| s.parse::<f64>().ok()) else {
                continue;
            };
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
        type GaikuKey = (String, String, String);
        let mut gaiku_groups: HashMap<GaikuKey, Vec<(i32, i32, f64, f64)>> = HashMap::new();
        for row in &gaiku_rows {
            if row.get("都道府県名").map(|s| s.as_str()) != Some("東京都") {
                continue;
            }
            let muni = row.get("市区町村名").cloned().unwrap_or_default();
            let oaza =
                normalize_addr(&row.get("大字・丁目名").cloned().unwrap_or_default());
            let block = row.get("街区符号・地番").cloned().unwrap_or_default();
            let rep_flag: i32 = row
                .get("代表フラグ")
                .and_then(|s| s.parse().ok())
                .unwrap_or(0);
            let addr_flag: i32 = row
                .get("住居表示フラグ")
                .and_then(|s| s.parse().ok())
                .unwrap_or(0);
            let Some(lat) = row.get("緯度").and_then(|s| s.parse::<f64>().ok()) else {
                continue;
            };
            let Some(lon) = row.get("経度").and_then(|s| s.parse::<f64>().ok()) else {
                continue;
            };
            gaiku_groups
                .entry((muni, oaza, block))
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

        Ok(Self {
            gaiku_index,
            oaza_first,
            muni_centroid,
        })
    }

    fn geocode(&self, address: &str) -> PyResult<(f64, f64, String)> {
        let addr = normalize_addr(address);
        let (muni_opt, _) = split_tokyo_municipality(&addr);
        let muni = muni_opt.ok_or_else(|| {
            pyo3::exceptions::PyValueError::new_err(format!(
                "東京都住所として解釈できません: {}",
                address
            ))
        })?;

        let (town, chome, block) = parse_town_chome_block(&addr);
        let mut gaiku_candidates: Vec<(String, i32)> = Vec::new();
        let mut oaza_candidates: Vec<String> = Vec::new();

        if let Some(ref t) = town {
            if let Some(c) = chome {
                if (0..=99).contains(&c) {
                    let oaza_chome = normalize_addr(&build_oaza_chome_name(t, c));
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

        Err(pyo3::exceptions::PyValueError::new_err(format!(
            "住所参照データで解決できません: {}",
            address
        )))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use tempfile::TempDir;

    fn init_python() {
        pyo3::prepare_freethreaded_python();
    }

    fn setup_test_csvs() -> (TempDir, String, String) {
        let dir = TempDir::new().unwrap();
        let oaza_path = dir.path().join("oaza.csv");
        let gaiku_path = dir.path().join("gaiku.csv");

        let mut f = fs::File::create(&oaza_path).unwrap();
        writeln!(f, "都道府県名,市区町村名,大字町丁目名,緯度,経度").unwrap();
        writeln!(f, "東京都,中央区,日本橋兜町,35.670001,139.770001").unwrap();
        writeln!(f, "東京都,港区,六本木三丁目,35.660001,139.730001").unwrap();
        writeln!(f, "東京都,千代田区,五番町,35.689685,139.733989").unwrap();
        writeln!(f, "東京都,千代田区,二番町,35.686185,139.736126").unwrap();

        let mut f = fs::File::create(&gaiku_path).unwrap();
        writeln!(
            f,
            "都道府県名,市区町村名,大字・丁目名,街区符号・地番,代表フラグ,住居表示フラグ,緯度,経度"
        )
        .unwrap();
        writeln!(f, "東京都,中央区,日本橋兜町,11,1,1,35.680001,139.780001").unwrap();
        writeln!(f, "東京都,港区,六本木三丁目,4,1,1,35.665001,139.735001").unwrap();
        writeln!(f, "東京都,千代田区,五番町,4,1,1,35.689856,139.734955").unwrap();
        writeln!(f, "東京都,千代田区,二番町,3,1,1,35.685929,139.737800").unwrap();

        (
            dir,
            oaza_path.to_str().unwrap().to_string(),
            gaiku_path.to_str().unwrap().to_string(),
        )
    }

    #[test]
    fn test_geocode_bango_without_chome() {
        init_python();
        let (_dir, oaza, gaiku) = setup_test_csvs();
        let gc = TokyoGeocoder::new(&oaza, &gaiku).unwrap();
        let (lat, lon, level) = gc.geocode("東京都中央区日本橋兜町11番5号").unwrap();
        assert_eq!(level, "gaiku");
        assert!((lat - 35.680001).abs() < 1e-5);
        assert!((lon - 139.780001).abs() < 1e-5);
    }

    #[test]
    fn test_geocode_hyphen_without_chome() {
        init_python();
        let (_dir, oaza, gaiku) = setup_test_csvs();
        let gc = TokyoGeocoder::new(&oaza, &gaiku).unwrap();
        let (lat, lon, level) = gc.geocode("東京都中央区日本橋兜町11-5").unwrap();
        assert_eq!(level, "gaiku");
        assert!((lat - 35.680001).abs() < 1e-5);
        assert!((lon - 139.780001).abs() < 1e-5);
    }

    #[test]
    fn test_geocode_town_only() {
        init_python();
        let (_dir, oaza, gaiku) = setup_test_csvs();
        let gc = TokyoGeocoder::new(&oaza, &gaiku).unwrap();
        let (lat, _, level) = gc.geocode("東京都中央区日本橋兜町").unwrap();
        assert_eq!(level, "oaza_chome");
        assert!((lat - 35.670001).abs() < 1e-5);
    }

    #[test]
    fn test_geocode_chome_hyphen() {
        init_python();
        let (_dir, oaza, gaiku) = setup_test_csvs();
        let gc = TokyoGeocoder::new(&oaza, &gaiku).unwrap();
        let (_, _, level) = gc.geocode("東京都港区六本木3-4-33").unwrap();
        assert_eq!(level, "gaiku");
    }

    #[test]
    fn test_geocode_bancho_gaiku() {
        init_python();
        let (_dir, oaza, gaiku) = setup_test_csvs();
        let gc = TokyoGeocoder::new(&oaza, &gaiku).unwrap();
        let (lat, lon, level) = gc.geocode("東京都千代田区五番町4番7号").unwrap();
        assert_eq!(level, "gaiku");
        assert!((lat - 35.689856).abs() < 1e-4);
        assert!((lon - 139.734955).abs() < 1e-4);
    }

    #[test]
    fn test_geocode_bancho_oaza() {
        init_python();
        let (_dir, oaza, gaiku) = setup_test_csvs();
        let gc = TokyoGeocoder::new(&oaza, &gaiku).unwrap();
        let (lat, _, level) = gc.geocode("東京都千代田区二番町").unwrap();
        assert_eq!(level, "oaza_chome");
        assert!((lat - 35.686185).abs() < 1e-4);
    }

    #[test]
    fn test_geocode_bancho_with_banchi() {
        init_python();
        let (_dir, oaza, gaiku) = setup_test_csvs();
        let gc = TokyoGeocoder::new(&oaza, &gaiku).unwrap();
        let (_, _, level) = gc.geocode("東京都千代田区二番町3番地").unwrap();
        assert_eq!(level, "gaiku");
    }
}
