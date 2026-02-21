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
        def __init__(self, geojson_path: str):
            gdf = gpd.read_file(geojson_path)
            # geometryはPoint想定
            self.lats = gdf.geometry.y.to_numpy(dtype=float)
            self.lons = gdf.geometry.x.to_numpy(dtype=float)
            self.prices = gdf["L01_008"].astype(float).to_numpy()

            l01_001 = gdf["L01_001"].astype(str)
            l01_002 = gdf["L01_002"].astype(str).str.zfill(3)
            l01_003 = gdf["L01_003"].astype(str).str.zfill(3)
            self.point_ids = (l01_001 + "-" + l01_002 + "-" + l01_003).to_numpy()
            self.landuse_kinds = gdf["L01_051"].fillna("").astype(str).to_numpy()
            self.point_idx_by_id = {str(pid): int(i) for i, pid in enumerate(self.point_ids)}

            self.geod = Geod(ellps="WGS84")

            # 平面直角座標 (EPSG:6677 = JGD2011 / Japan Plane IX — 東京都) への変換
            self._transformer = Transformer.from_crs("EPSG:4326", "EPSG:6677", always_xy=True)
            xs, ys = self._transformer.transform(self.lons, self.lats)
            self._plane_coords = np.column_stack([xs, ys])

            # 全点用 cKDTree
            self._tree_all = cKDTree(self._plane_coords)

            # 用途区分別サブツリー + グローバルインデックス
            self._landuse_trees: dict[str, tuple[cKDTree, np.ndarray]] = {}
            unique_kinds = set(self.landuse_kinds.tolist()) - {""}
            for kind in unique_kinds:
                mask = self.landuse_kinds == kind
                idx = np.where(mask)[0]
                if len(idx) > 0:
                    self._landuse_trees[kind] = (cKDTree(self._plane_coords[idx]), idx)

        def get_point_landuse_kind(self, point_id: str) -> str:
            idx = self.point_idx_by_id.get(point_id)
            if idx is None:
                return ""
            return str(self.landuse_kinds[idx])

        def get_landuse_kinds_for_ids(self, point_ids: list[str]) -> list[str]:
            return [self.get_point_landuse_kind(pid) for pid in point_ids]

        def _get_tree_and_index(self, landuse_kind: str | None) -> tuple[cKDTree, np.ndarray]:
            if landuse_kind and landuse_kind in self._landuse_trees:
                return self._landuse_trees[landuse_kind]
            return self._tree_all, np.arange(len(self.point_ids))

        def _to_plane(self, lat: float, lon: float) -> np.ndarray:
            x, y = self._transformer.transform(lon, lat)
            return np.array([x, y])

        def _ellipsoid_dists(self, lat: float, lon: float, global_indices: np.ndarray) -> np.ndarray:
            """Compute WGS84 ellipsoid distances for the given global indices."""
            _, _, dist = self.geod.inv(
                np.full(len(global_indices), lon),
                np.full(len(global_indices), lat),
                self.lons[global_indices],
                self.lats[global_indices],
            )
            return np.asarray(dist, dtype=float)

        def nearest(self, lat: float, lon: float, landuse_kind: str | None = None) -> PriceResult:
            tree, global_idx = self._get_tree_and_index(landuse_kind)
            pt = self._to_plane(lat, lon)
            # Query extra neighbours to handle tie-breaking by point_id
            _, local_indices = tree.query(pt, k=min(3, len(global_idx)))
            local_indices = np.atleast_1d(local_indices)
            cands_global = global_idx[local_indices]

            # 楕円体距離で正確に最近傍を決定
            dists = self._ellipsoid_dists(lat, lon, cands_global)
            min_dist = float(np.min(dists))
            ties = np.where(np.isclose(dists, min_dist))[0]
            if len(ties) == 1:
                idx0 = int(cands_global[ties[0]])
            else:
                tie_globals = cands_global[ties]
                ids = self.point_ids[tie_globals]
                idx0 = int(tie_globals[np.argmin(ids)])

            dist_m = float(self._ellipsoid_dists(lat, lon, np.array([idx0]))[0])
            return PriceResult(
                unit_price=int(round(self.prices[idx0])),
                nearest_id=str(self.point_ids[idx0]),
                nearest_dist_m=dist_m,
                knn_ids=[str(self.point_ids[idx0])],
                knn_dist_m=[dist_m],
                knn_prices=[int(round(self.prices[idx0]))],
            )

        def idw(
            self,
            lat: float,
            lon: float,
            k: int = 3,
            p: int = 3,
            eps: float = 1.0,
            landuse_kind: str | None = None,
        ) -> PriceResult:
            if k <= 0:
                raise ValueError("kは1以上")
            tree, global_idx = self._get_tree_and_index(landuse_kind)
            pt = self._to_plane(lat, lon)
            k2 = min(k, len(global_idx))
            # Query extra candidates for tie-breaking
            k_query = min(k2 + 2, len(global_idx))
            _, local_indices = tree.query(pt, k=k_query)
            local_indices = np.atleast_1d(local_indices)
            cands_global = global_idx[local_indices]

            # 楕円体距離を計算
            dists = self._ellipsoid_dists(lat, lon, cands_global)

            # 距離昇順→point_id昇順でソートし上位k2件を選択
            order = np.lexsort((self.point_ids[cands_global], dists))
            selected = cands_global[order[:k2]]
            d = self._ellipsoid_dists(lat, lon, selected)

            w = 1.0 / np.power(d + eps, p)
            unit = float(np.sum(w * self.prices[selected]) / np.sum(w))
            idx0 = int(selected[0])
            return PriceResult(
                unit_price=int(round(unit)),
                nearest_id=str(self.point_ids[idx0]),
                nearest_dist_m=float(d[0]),
                knn_ids=[str(x) for x in self.point_ids[selected].tolist()],
                knn_dist_m=[float(x) for x in d.tolist()],
                knn_prices=[int(round(x)) for x in self.prices[selected].tolist()],
            )
