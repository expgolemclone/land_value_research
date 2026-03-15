import unittest

from src.web_address_research import WebAddressResearcher


class TestScore(unittest.TestCase):
    """Test the _score static method scoring logic."""

    def test_municipality_match_adds_20(self) -> None:
        score = WebAddressResearcher._score(
            site_name="本社",
            location_short="東京都中央区",
            addr="東京都中央区日本橋1丁目1-1",
            page_text="",
        )
        # muni match (+20), loc match (+30), 丁目 (+10), 番地 (+20)
        self.assertGreaterEqual(score, 20)

    def test_municipality_mismatch_subtracts_40(self) -> None:
        score = WebAddressResearcher._score(
            site_name="本社",
            location_short="東京都港区",
            addr="東京都中央区日本橋1丁目1-1",
            page_text="",
        )
        # muni mismatch (-40)
        self.assertLess(score, 40)

    def test_detailed_address_adds_points(self) -> None:
        score_detailed = WebAddressResearcher._score(
            site_name="本社",
            location_short="東京都中央区",
            addr="東京都中央区日本橋1丁目15番3号",
            page_text="",
        )
        score_coarse = WebAddressResearcher._score(
            site_name="本社",
            location_short="東京都中央区",
            addr="東京都中央区日本橋1丁目",
            page_text="",
        )
        # Detailed address should score higher than chome-only
        self.assertGreater(score_detailed, score_coarse)

    def test_chome_only_penalized(self) -> None:
        score = WebAddressResearcher._score(
            site_name="本社",
            location_short="東京都中央区",
            addr="東京都中央区日本橋1丁目",
            page_text="",
        )
        # Has 丁目 (+10) but ends with 丁目 (-5) → net +5 for that component
        self.assertGreater(score, 0)

    def test_site_name_in_context_adds_40(self) -> None:
        addr = "東京都中央区日本橋1-2-3"
        # Put addr and site name in the page text
        page_text = f"本社所在地: {addr} 当社の本社"
        score_with = WebAddressResearcher._score(
            site_name="本社",
            location_short="東京都中央区",
            addr=addr,
            page_text=page_text,
        )
        score_without = WebAddressResearcher._score(
            site_name="本社",
            location_short="東京都中央区",
            addr=addr,
            page_text="",
        )
        self.assertGreater(score_with, score_without)

    def test_empty_location_short(self) -> None:
        # Should not crash with empty location
        score = WebAddressResearcher._score(
            site_name="本社",
            location_short="",
            addr="東京都中央区日本橋1-2-3",
            page_text="",
        )
        self.assertIsInstance(score, int)


if __name__ == "__main__":
    unittest.main()
