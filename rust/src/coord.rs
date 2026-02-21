use geographiclib_rs::{Geodesic, InverseGeodesic};
use once_cell::sync::Lazy;
use proj4rs::Proj;

static PROJ_FROM: Lazy<Proj> =
    Lazy::new(|| Proj::from_proj_string("+proj=longlat +datum=WGS84").unwrap());

static PROJ_TO: Lazy<Proj> = Lazy::new(|| {
    Proj::from_proj_string(
        "+proj=tmerc +lat_0=36 +lon_0=139.833333333333 +k=0.9999 \
         +x_0=0 +y_0=0 +ellps=GRS80 +units=m +no_defs",
    )
    .unwrap()
});

static GEOD: Lazy<Geodesic> = Lazy::new(Geodesic::wgs84);

/// (lon, lat) → (x, y) in EPSG:6677 (JGD2011 / Japan Plane Rectangular IX)
pub fn lonlat_to_plane(lon: f64, lat: f64) -> (f64, f64) {
    let mut point = (lon.to_radians(), lat.to_radians(), 0.0);
    proj4rs::transform::transform(&PROJ_FROM, &PROJ_TO, &mut point).unwrap();
    (point.0, point.1)
}

/// WGS84 楕円体上の2点間距離 (m)
pub fn ellipsoid_distance(lat1: f64, lon1: f64, lat2: f64, lon2: f64) -> f64 {
    <Geodesic as InverseGeodesic<f64>>::inverse(&GEOD, lat1, lon1, lat2, lon2)
}

/// 1点 (lat, lon) から複数点への楕円体距離を一括計算
pub fn ellipsoid_distances(
    lat: f64,
    lon: f64,
    target_lats: &[f64],
    target_lons: &[f64],
) -> Vec<f64> {
    target_lats
        .iter()
        .zip(target_lons.iter())
        .map(|(&t_lat, &t_lon)| {
            <Geodesic as InverseGeodesic<f64>>::inverse(&GEOD, lat, lon, t_lat, t_lon)
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_lonlat_to_plane_tokyo_station() {
        let (x, y) = lonlat_to_plane(139.7671, 35.6812);
        assert!(x < 0.0, "x should be negative: {x}");
        assert!(y < 0.0, "y should be negative: {y}");
        assert!((x.abs() - 6000.0).abs() < 2000.0, "x = {x}");
        assert!((y.abs() - 35000.0).abs() < 2000.0, "y = {y}");
    }

    #[test]
    fn test_ellipsoid_distance_known_pair() {
        // 東京駅 (35.6812, 139.7671) ↔ 新宿駅 (35.6896, 139.7006)
        let d = ellipsoid_distance(35.6812, 139.7671, 35.6896, 139.7006);
        // geographiclib gives ~6091m
        assert!(d > 5000.0 && d < 7000.0, "distance = {d}");
    }

    #[test]
    fn test_ellipsoid_distance_same_point() {
        let d = ellipsoid_distance(35.6812, 139.7671, 35.6812, 139.7671);
        assert!(d.abs() < 1e-3, "distance = {d}");
    }

    #[test]
    fn test_ellipsoid_distances_batch() {
        let dists = ellipsoid_distances(
            35.6812,
            139.7671,
            &[35.6812, 35.6896],
            &[139.7671, 139.7006],
        );
        assert_eq!(dists.len(), 2);
        assert!(dists[0].abs() < 1e-3);
        assert!(dists[1] > 5000.0 && dists[1] < 7000.0);
    }
}
