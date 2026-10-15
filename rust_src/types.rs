use pyo3::prelude::*;

/// Python の PriceResult dataclass と同等の構造体
#[pyclass(frozen, get_all, skip_from_py_object)]
#[derive(Clone, Debug)]
pub struct PriceResult {
    pub unit_price: i64,
    pub nearest_id: String,
    pub nearest_dist_m: f64,
    pub knn_ids: Vec<String>,
    pub knn_dist_m: Vec<f64>,
    pub knn_prices: Vec<i64>,
}

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
        Self {
            unit_price,
            nearest_id,
            nearest_dist_m,
            knn_ids,
            knn_dist_m,
            knn_prices,
        }
    }
}
