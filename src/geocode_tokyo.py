from __future__ import annotations

import logging

import pandas as pd

from src.jp_address import build_oaza_chome_name, normalize_addr, parse_town_chome_block, split_tokyo_municipality

logger = logging.getLogger(__name__)


class TokyoGeocoder:
    def __init__(self, oaza_csv: str, gaiku_csv: str):
        # CP932/UTF-8両対応(決定的: CP932->UTF-8の順で読む)
        self.oaza = self._read_csv_any(oaza_csv)
        self.gaiku = self._read_csv_any(gaiku_csv)
        self._build_indexes()

    @staticmethod
    def _read_csv_any(path: str) -> pd.DataFrame:
        for enc in ["cp932", "utf-8"]:
            try:
                return pd.read_csv(path, encoding=enc, low_memory=False)
            except Exception:
                continue
        # 最後にデフォルト
        return pd.read_csv(path, low_memory=False)

    def _build_indexes(self) -> None:
        oaza_t = self.oaza[self.oaza["都道府県名"] == "東京都"].copy()
        gaiku_t = self.gaiku[self.gaiku["都道府県名"] == "東京都"].copy()

        self._oaza_first: dict[tuple[str, str], tuple[float, float]] = {}
        for (muni, oaza_name), sub in oaza_t.groupby(["市区町村名", "大字町丁目名"], sort=False):
            sub2 = sub.sort_values(by=["緯度", "経度"], ascending=[True, True])
            row = sub2.iloc[0]
            self._oaza_first[(str(muni), str(oaza_name))] = (float(row["緯度"]), float(row["経度"]))

        self._muni_centroid: dict[str, tuple[float, float]] = {}
        muni_mean = oaza_t.groupby("市区町村名", sort=False)[["緯度", "経度"]].mean()
        for muni, row in muni_mean.iterrows():
            self._muni_centroid[str(muni)] = (float(row["緯度"]), float(row["経度"]))

        self._gaiku_index: dict[tuple[str, str, str], tuple[float, float]] = {}
        gaiku_t["街区符号・地番_str"] = gaiku_t["街区符号・地番"].astype(str)
        for (muni, oaza_name, block), sub in gaiku_t.groupby(
            ["市区町村名", "大字・丁目名", "街区符号・地番_str"], sort=False
        ):
            sub2 = sub.sort_values(
                by=["代表フラグ", "住居表示フラグ", "緯度", "経度"],
                ascending=[False, False, True, True],
            )
            row = sub2.iloc[0]
            self._gaiku_index[(str(muni), str(oaza_name), str(block))] = (float(row["緯度"]), float(row["経度"]))

    def geocode(self, address: str) -> tuple[float, float, str]:
        """東京都内の住所を緯度経度へ.

        戻り値:
          (lat, lon, level)
          level: "gaiku" or "oaza_chome" or "unknown"
        """

        addr = normalize_addr(address)
        muni, _ = split_tokyo_municipality(addr)
        if not muni:
            raise ValueError(f"東京都住所として解釈できません: {address}")

        town, chome, block = parse_town_chome_block(addr)
        gaiku_candidates: list[tuple[str, int]] = []
        oaza_candidates: list[str] = []

        if town and chome is not None:
            if 0 <= chome <= 99:
                oaza_chome = build_oaza_chome_name(town, chome)
                oaza_candidates.append(oaza_chome)
                if block is not None:
                    gaiku_candidates.append((oaza_chome, block))
                    # 例: 日本橋兜町11-5 は town=日本橋兜町, block=11 で解決できる
                    gaiku_candidates.append((town, chome))
            else:
                logger.warning("丁目値が範囲外(0-99)のためスキップ: chome=%d, address=%s", chome, address)
            # ハイフン住所は「丁目あり」と「丁目なし」が混在するため town も候補に含める
            oaza_candidates.append(town)
        elif town:
            oaza_candidates.append(town)
            if block is not None:
                gaiku_candidates.append((town, block))

        # 順序を維持して重複除去
        gaiku_candidates = list(dict.fromkeys(gaiku_candidates))
        oaza_candidates = list(dict.fromkeys(oaza_candidates))

        # 街区優先
        for oaza_name, gaiku_block in gaiku_candidates:
            hit = self._gaiku_index.get((muni, oaza_name, str(gaiku_block)))
            if hit is not None:
                return hit[0], hit[1], "gaiku"

        # 町丁目フォールバック
        for oaza_name in oaza_candidates:
            hit = self._oaza_first.get((muni, oaza_name))
            if hit is not None:
                return hit[0], hit[1], "oaza_chome"

        # 区市までしか無い場合のフォールバック(区市内の大字町丁目の平均)
        hit = self._muni_centroid.get(muni)
        if hit is not None:
            return hit[0], hit[1], "muni_centroid"

        raise ValueError(f"住所参照データで解決できません: {address}")
