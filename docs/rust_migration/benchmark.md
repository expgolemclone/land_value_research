# Rust Migration Benchmark Results

Date: 2026-02-21
Environment: Windows 11, Python 3.12.10, Rust 1.x (PyO3 0.24)

## Initialization Performance

| Operation | Python | Rust | Speedup |
|-----------|--------|------|---------|
| GeoJSON load + KDTree build | 1.179s | 0.158s | **7.5x** |
| CSV load + geocoder index build | 0.637s (CSV only) | 1.464s (CSV + full index) | N/A (*) |

(*) Python timing only measures `pd.read_csv()` without the subsequent `groupby`/`sort` index construction, so it is not directly comparable. The Rust implementation includes the complete CSV parse + index build in a single step.

## Per-Operation Performance (geocode + IDW)

| Operation | Rust |
|-----------|------|
| 500 geocode+IDW operations | 0.006s |
| Per-operation latency | **0.01 ms** |

Note: Python per-op benchmark could not be measured directly because the Rust backend is active and replaces the Python implementation at import time.

## Key Observations

1. **GeoJSON + KDTree initialization is 7.5x faster** in Rust (0.158s vs 1.179s). This avoids geopandas/fiona overhead and uses kiddo v4 KDTree directly.
2. **geocode + IDW per-operation latency is sub-millisecond** in Rust. For 3,618 companies with ~5 sites each (~18,000 ops), this adds approximately 0.2s total.
3. **Lazy static caching** of `Proj` and `Geodesic` instances in coord.rs avoids repeated initialization overhead.
4. **Memory**: Rust implementation avoids numpy/pandas/geopandas memory overhead for the spatial computation path.

## Optimization Applied

- `Lazy<Proj>` and `Lazy<Geodesic>` static instances (coord.rs) - avoids per-call initialization
- UFCS `<Geodesic as InverseGeodesic<f64>>::inverse()` for correct scalar distance return
- kiddo v4 `nearest_n` with `SquaredEuclidean` metric for KDTree queries
- `HashMap`-based O(1) lookup indexes for geocoder (gaiku, oaza, muni)
