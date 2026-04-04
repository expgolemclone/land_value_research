"""Tests for post-pipeline cleanup logic."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.merge_address_patches import merge_patches_safe


class TestMergePatchesSafe(unittest.TestCase):
    """Tests for merge_patches_safe()."""

    def test_no_patch_dir(self):
        """Returns 0 when patch directory does not exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = merge_patches_safe(
                patch_dir=Path(tmpdir) / "nonexistent",
                overrides_file=Path(tmpdir) / "overrides.yaml",
            )
            self.assertEqual(result, 0)

    def test_empty_patch_dir(self):
        """Returns 0 when patch directory has no YAML files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            patch_dir = Path(tmpdir) / "patches"
            patch_dir.mkdir()
            result = merge_patches_safe(
                patch_dir=patch_dir,
                overrides_file=Path(tmpdir) / "overrides.yaml",
            )
            self.assertEqual(result, 0)

    def test_merges_patch_file(self):
        """Merges a patch file into overrides and deletes it."""
        with tempfile.TemporaryDirectory() as tmpdir:
            patch_dir = Path(tmpdir) / "patches"
            patch_dir.mkdir()
            overrides_file = Path(tmpdir) / "overrides.yaml"

            # Create a patch file
            patch_file = patch_dir / "1234.yaml"
            patch_file.write_text(
                "'1234':\n  本社: 東京都千代田区丸の内1-1-1\n",
                encoding="utf-8",
            )

            result = merge_patches_safe(
                patch_dir=patch_dir,
                overrides_file=overrides_file,
            )

            self.assertEqual(result, 1)
            self.assertFalse(patch_file.exists(), "Patch file should be deleted")
            self.assertTrue(overrides_file.exists(), "Overrides file should be created")

            content = overrides_file.read_text(encoding="utf-8")
            self.assertIn("1234", content)
            self.assertIn("丸の内", content)

    def test_merges_into_existing_overrides(self):
        """Merges patches into an existing overrides file without losing data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            patch_dir = Path(tmpdir) / "patches"
            patch_dir.mkdir()
            overrides_file = Path(tmpdir) / "overrides.yaml"

            # Existing overrides
            overrides_file.write_text(
                "'9999':\n  工場: 東京都港区芝公園4-2-8\n",
                encoding="utf-8",
            )

            # New patch
            (patch_dir / "1234.yaml").write_text(
                "'1234':\n  本社: 東京都千代田区丸の内1-1-1\n",
                encoding="utf-8",
            )

            merge_patches_safe(patch_dir=patch_dir, overrides_file=overrides_file)

            content = overrides_file.read_text(encoding="utf-8")
            self.assertIn("9999", content)
            self.assertIn("1234", content)

    def test_skips_empty_patch(self):
        """Skips empty YAML files but still returns count of merged files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            patch_dir = Path(tmpdir) / "patches"
            patch_dir.mkdir()

            (patch_dir / "empty.yaml").write_text("", encoding="utf-8")
            (patch_dir / "1234.yaml").write_text(
                "'1234':\n  本社: 東京都千代田区丸の内1-1-1\n",
                encoding="utf-8",
            )

            result = merge_patches_safe(
                patch_dir=patch_dir,
                overrides_file=Path(tmpdir) / "overrides.yaml",
            )

            # Only 1234.yaml is merged, empty.yaml is skipped
            self.assertEqual(result, 1)


class TestPostPipelineCleanup(unittest.TestCase):
    """Tests for _post_pipeline_cleanup() from run.py."""

    def test_prune_old_logs(self):
        """Keeps only the latest N log files."""
        from run import _post_pipeline_cleanup

        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir) / "data" / "output" / "run_logs"
            log_dir.mkdir(parents=True)
            config_dir = Path(tmpdir) / "config"
            config_dir.mkdir()

            # Create 7 log files with sortable names
            names = [
                "20260101_000000.log",
                "20260102_000000.log",
                "20260103_000000.log",
                "20260104_000000.log",
                "20260105_000000.log",
                "20260106_000000.log",
                "20260107_000000.log",
            ]
            for name in names:
                (log_dir / name).write_text("log", encoding="utf-8")

            _post_pipeline_cleanup(tmpdir, keep_logs=5)

            remaining = sorted(f.name for f in log_dir.glob("*.log"))
            self.assertEqual(len(remaining), 5)
            # Oldest 2 should be deleted
            self.assertNotIn("20260101_000000.log", remaining)
            self.assertNotIn("20260102_000000.log", remaining)
            # Latest 5 should remain
            self.assertIn("20260103_000000.log", remaining)
            self.assertIn("20260107_000000.log", remaining)

    def test_fewer_logs_than_keep(self):
        """Does not delete anything when fewer logs than keep_logs."""
        from run import _post_pipeline_cleanup

        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir) / "data" / "output" / "run_logs"
            log_dir.mkdir(parents=True)
            config_dir = Path(tmpdir) / "config"
            config_dir.mkdir()

            (log_dir / "20260101_000000.log").write_text("log", encoding="utf-8")

            _post_pipeline_cleanup(tmpdir, keep_logs=5)

            remaining = list(log_dir.glob("*.log"))
            self.assertEqual(len(remaining), 1)

    def test_delete_bak_files(self):
        """Deletes .bak files from config/."""
        from run import _post_pipeline_cleanup

        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = Path(tmpdir) / "split-address"
            docs_dir.mkdir()
            config_dir = Path(tmpdir) / "config"
            config_dir.mkdir()

            bak = config_dir / "company_master.yaml.bak"
            bak.write_text("backup", encoding="utf-8")

            _post_pipeline_cleanup(tmpdir, keep_logs=5)

            self.assertFalse(bak.exists(), ".bak file should be deleted")

    def test_no_bak_no_error(self):
        """No error when no .bak files exist."""
        from run import _post_pipeline_cleanup

        with tempfile.TemporaryDirectory() as tmpdir:
            docs_dir = Path(tmpdir) / "split-address"
            docs_dir.mkdir()
            config_dir = Path(tmpdir) / "config"
            config_dir.mkdir()

            # Should not raise
            _post_pipeline_cleanup(tmpdir, keep_logs=5)

    def test_continues_on_partial_failure(self):
        """Cleanup continues even if one step fails."""
        from run import _post_pipeline_cleanup

        with tempfile.TemporaryDirectory() as tmpdir:
            # split-address/ missing — log pruning will fail, but .bak deletion should still run
            config_dir = Path(tmpdir) / "config"
            config_dir.mkdir()

            bak = config_dir / "test.bak"
            bak.write_text("backup", encoding="utf-8")

            _post_pipeline_cleanup(tmpdir, keep_logs=5)

            self.assertFalse(bak.exists(), ".bak should be deleted even if log pruning fails")


if __name__ == "__main__":
    unittest.main()
