from __future__ import annotations

from dataclasses import dataclass

import geopandas as gpd
import numpy as np
from pyproj import Geod


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

    def get_point_landuse_kind(self, point_id: str) -> str:
        idx = self.point_idx_by_id.get(point_id)
        if idx is None:
            return ""
        return str(self.landuse_kinds[idx])

    def get_landuse_kinds_for_ids(self, point_ids: list[str]) -> list[str]:
        return [self.get_point_landuse_kind(pid) for pid in point_ids]

    def _candidate_index_by_landuse(self, landuse_kind: str | None = None) -> np.ndarray:
        if not landuse_kind:
            return np.arange(len(self.point_ids))
        mask = self.landuse_kinds == str(landuse_kind)
        if np.any(mask):
            return np.where(mask)[0]
        return np.arange(len(self.point_ids))

    def _dist_all(self, lat: float, lon: float) -> np.ndarray:
        # pyproj.Geod.invは (lon1, lat1, lon2, lat2)
        _, _, dist = self.geod.inv(
            np.full_like(self.lons, lon),
            np.full_like(self.lats, lat),
            self.lons,
            self.lats,
        )
        return dist

    def nearest(self, lat: float, lon: float, landuse_kind: str | None = None) -> PriceResult:
        dist = self._dist_all(lat, lon)
        cand_idx = self._candidate_index_by_landuse(landuse_kind=landuse_kind)
        cand_dist = dist[cand_idx]
        min_dist = float(np.min(cand_dist))
        cands = cand_idx[np.where(cand_dist == min_dist)[0]]
        if len(cands) == 1:
            idx0 = int(cands[0])
        else:
            ids = self.point_ids[cands]
            idx0 = int(cands[np.argmin(ids)])
        return PriceResult(
            unit_price=int(round(self.prices[idx0])),
            nearest_id=str(self.point_ids[idx0]),
            nearest_dist_m=float(dist[idx0]),
            knn_ids=[str(self.point_ids[idx0])],
            knn_dist_m=[float(dist[idx0])],
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
        dist = self._dist_all(lat, lon)
        cand_idx = self._candidate_index_by_landuse(landuse_kind=landuse_kind)
        dist_cand = dist[cand_idx]
        n = len(dist_cand)
        k2 = min(k, n)
        kth_dist = float(np.partition(dist_cand, k2 - 1)[k2 - 1])
        cands = np.where(dist_cand <= kth_dist)[0]
        cands_global = cand_idx[cands]
        cands_order = np.lexsort((self.point_ids[cands_global], dist[cands_global]))
        idx = cands_global[cands_order][:k2]
        d = dist[idx]
        w = 1.0 / np.power(d + eps, p)
        unit = float(np.sum(w * self.prices[idx]) / np.sum(w))
        idx0 = int(idx[0])
        return PriceResult(
            unit_price=int(round(unit)),
            nearest_id=str(self.point_ids[idx0]),
            nearest_dist_m=float(dist[idx0]),
            knn_ids=[str(x) for x in self.point_ids[idx].tolist()],
            knn_dist_m=[float(x) for x in d.tolist()],
            knn_prices=[int(round(x)) for x in self.prices[idx].tolist()],
        )
