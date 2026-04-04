import os
import tempfile
import textwrap
import unittest

from src.company_config import (
    SiteSplitEntry,
    _allocate_book_values,
    _parse_split_entries,
    load_address_overrides,
    load_company_master,
)
from src.pdf_extract import FacilityLand


class TestLoadCompanyMaster(unittest.TestCase):
    def test_load_valid_yaml(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
            f.write(
                '"1234":\n  company_name: "テスト株式会社"\n  securities_report_pdf_url: "https://example.com/test.pdf"\n'
            )
            path = f.name
        try:
            result = load_company_master(path)
            self.assertIn("1234", result)
            self.assertEqual(result["1234"]["company_name"], "テスト株式会社")
        finally:
            os.unlink(path)

    def test_load_missing_file(self) -> None:
        result = load_company_master("/nonexistent/path.yaml")
        self.assertEqual(result, {})

    def test_load_empty_yaml(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
            f.write("")
            path = f.name
        try:
            result = load_company_master(path)
            self.assertEqual(result, {})
        finally:
            os.unlink(path)


class TestLoadCompanyMasterMalformed(unittest.TestCase):
    def test_list_yaml_returns_empty(self) -> None:
        """Top-level YAML is a list, not a dict."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
            f.write("- item1\n- item2\n")
            path = f.name
        try:
            result = load_company_master(path)
            self.assertEqual(result, {})
        finally:
            os.unlink(path)

    def test_scalar_yaml_returns_empty(self) -> None:
        """Top-level YAML is a scalar string."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
            f.write("just a string\n")
            path = f.name
        try:
            result = load_company_master(path)
            self.assertEqual(result, {})
        finally:
            os.unlink(path)


class TestLoadAddressOverrides(unittest.TestCase):
    def test_load_valid(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
            f.write('"1234":\n  "本社": "東京都千代田区丸の内1-9-2"\n')
            path = f.name
        try:
            result = load_address_overrides(path)
            self.assertIn("1234", result)
            self.assertEqual(result["1234"]["本社"], "東京都千代田区丸の内1-9-2")
        finally:
            os.unlink(path)

    def test_load_missing_file(self) -> None:
        result = load_address_overrides("/nonexistent/path.yaml")
        self.assertEqual(result, {})


class TestLoadAddressOverridesMalformed(unittest.TestCase):
    def test_list_yaml_returns_empty(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
            f.write("- item1\n- item2\n")
            path = f.name
        try:
            result = load_address_overrides(path)
            self.assertEqual(result, {})
        finally:
            os.unlink(path)

    def test_non_dict_mapping_skipped(self) -> None:
        """A code whose value is a list instead of a dict should be skipped."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
            f.write('"1234":\n  - "item1"\n  - "item2"\n"5678":\n  "本社": "東京都"\n')
            path = f.name
        try:
            result = load_address_overrides(path)
            self.assertNotIn("1234", result)
            self.assertIn("5678", result)
        finally:
            os.unlink(path)


class TestLoadAddressOverridesSplit(unittest.TestCase):
    def test_load_split_entries(self) -> None:
        """List values are parsed as list[SiteSplitEntry]."""
        yaml_content = textwrap.dedent("""\
            '1234':
              本社他:
                - name: 本社
                  address: 東京都港区芝5丁目33-1
                  area_m2: 5000
                  book_value_yen: 1000000000
                - name: 倉庫
                  address: 東京都大田区城南島2丁目6-1
                  area_m2: 22000
        """)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
            f.write(yaml_content)
            path = f.name
        try:
            result = load_address_overrides(path)
            self.assertIn("1234", result)
            entries = result["1234"]["本社他"]
            self.assertIsInstance(entries, list)
            self.assertEqual(len(entries), 2)
            self.assertIsInstance(entries[0], SiteSplitEntry)
            self.assertEqual(entries[0].name, "本社")
            self.assertEqual(entries[0].address, "東京都港区芝5丁目33-1")
            self.assertAlmostEqual(entries[0].area_m2, 5000.0)
            self.assertAlmostEqual(entries[0].book_value_yen, 1_000_000_000.0)
            self.assertEqual(entries[1].name, "倉庫")
            self.assertIsNone(entries[1].book_value_yen)
        finally:
            os.unlink(path)

    def test_mixed_string_and_split(self) -> None:
        """String and list values coexist under the same company code."""
        yaml_content = textwrap.dedent("""\
            '1234':
              本社: 東京都千代田区丸の内1-9-2
              支店他:
                - name: 新宿支店
                  address: 東京都新宿区西新宿1-1-1
                  area_m2: 3000
        """)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
            f.write(yaml_content)
            path = f.name
        try:
            result = load_address_overrides(path)
            self.assertIsInstance(result["1234"]["本社"], str)
            self.assertIsInstance(result["1234"]["支店他"], list)
        finally:
            os.unlink(path)

    def test_split_missing_required_field_raises(self) -> None:
        """Missing name/address/area_m2 in split entry raises ValueError."""
        yaml_content = textwrap.dedent("""\
            '1234':
              本社他:
                - name: 本社
                  area_m2: 5000
        """)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
            f.write(yaml_content)
            path = f.name
        try:
            with self.assertRaises(ValueError) as cm:
                load_address_overrides(path)
            self.assertIn("address", str(cm.exception))
        finally:
            os.unlink(path)

    def test_empty_split_list_raises(self) -> None:
        """Empty list value raises ValueError."""
        yaml_content = textwrap.dedent("""\
            '1234':
              本社他: []
        """)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
            f.write(yaml_content)
            path = f.name
        try:
            with self.assertRaises(ValueError):
                load_address_overrides(path)
        finally:
            os.unlink(path)


class TestParseSplitEntriesNullBookValue(unittest.TestCase):
    def test_null_book_value_yen_treated_as_none(self) -> None:
        """book_value_yen: null should be parsed as None, not crash."""
        entries = _parse_split_entries(
            "0000",
            "site",
            [{"name": "A", "address": "x", "area_m2": 1, "book_value_yen": None}],
        )
        self.assertEqual(len(entries), 1)
        self.assertIsNone(entries[0].book_value_yen)


class TestAllocateBookValuesNegative(unittest.TestCase):
    def test_specified_exceeds_original_raises(self) -> None:
        """Sum of specified book values exceeding original should raise ValueError."""
        orig = FacilityLand(
            site_name="S",
            location_short="x",
            land_area_m2=100,
            land_book_value_yen=10,
        )
        entries = [
            SiteSplitEntry(name="a", address="x", area_m2=50, book_value_yen=20),
            SiteSplitEntry(name="b", address="y", area_m2=50, book_value_yen=None),
        ]
        with self.assertRaises(ValueError):
            _allocate_book_values(orig, entries)


if __name__ == "__main__":
    unittest.main()
