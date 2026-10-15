use pyo3::prelude::*;

mod coord;
mod geocode_tokyo;
mod jp_address;
mod landprice_tokyo;
mod types;

/// Rust 拡張が利用可能かどうかを返す
#[pyfunction]
fn rust_available() -> bool {
    true
}

/// land_value_core Python モジュール
#[pymodule]
fn land_value_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(rust_available, m)?)?;
    m.add_class::<types::PriceResult>()?;
    m.add_class::<landprice_tokyo::LandPriceTokyo>()?;
    m.add_class::<geocode_tokyo::TokyoGeocoder>()?;
    m.add_function(wrap_pyfunction!(jp_address::py_normalize_addr, m)?)?;
    m.add_function(wrap_pyfunction!(
        jp_address::py_split_tokyo_municipality,
        m
    )?)?;
    m.add_function(wrap_pyfunction!(jp_address::py_parse_town_chome_block, m)?)?;
    m.add_function(wrap_pyfunction!(jp_address::py_num_to_kanji, m)?)?;
    m.add_function(wrap_pyfunction!(jp_address::py_build_oaza_chome_name, m)?)?;
    m.add_function(wrap_pyfunction!(jp_address::py_kanji_to_int, m)?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use encoding_rs::SHIFT_JIS;

    #[test]
    fn test_cp932_decode() {
        let bytes = b"\x93\x8c\x8b\x9e\x93s"; // "東京都" in CP932
        let (decoded, _, had_errors) = SHIFT_JIS.decode(bytes);
        assert!(!had_errors);
        assert_eq!(decoded, "東京都");
    }
}
