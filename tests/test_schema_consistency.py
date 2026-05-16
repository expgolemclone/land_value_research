"""Schema consistency tests.

These tests ensure that every consumer of column definitions stays in sync
with the single source of truth in src/schema.py.  If a column is added,
renamed, or reordered in schema.py and a downstream module is not updated,
one of these tests will fail.
"""

import unittest

from src.schema import OUTPUT_COLUMNS, OutputRow


class TestOutputColumnsConsistency(unittest.TestCase):
    def test_output_row_keys_match_output_columns(self) -> None:
        """OutputRow TypedDict keys must equal OUTPUT_COLUMNS (same set, same order)."""
        row_keys = tuple(OutputRow.__annotations__)
        self.assertEqual(row_keys, OUTPUT_COLUMNS)

    def test_no_duplicate_output_columns(self) -> None:
        self.assertEqual(len(OUTPUT_COLUMNS), len(set(OUTPUT_COLUMNS)))

    def test_output_column_count(self) -> None:
        """OUTPUT_COLUMNS must have exactly 33 entries."""
        self.assertEqual(len(OUTPUT_COLUMNS), 33)


class TestRunModuleUsesSchema(unittest.TestCase):
    def test_run_fieldnames_match_schema(self) -> None:
        """run.OUTPUT_FIELDNAMES must be derived from schema.OUTPUT_COLUMNS."""
        from run import OUTPUT_FIELDNAMES

        self.assertEqual(tuple(OUTPUT_FIELDNAMES), OUTPUT_COLUMNS)


if __name__ == "__main__":
    unittest.main()
