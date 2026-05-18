from __future__ import annotations

from pathlib import Path

from src.utils import open_csv


def test_open_csv_reads_cp932_after_utf8_attempt(tmp_path: Path) -> None:
    path = tmp_path / "cp932.csv"
    path.write_bytes("会社名\nテスト\n".encode("cp932"))

    with open_csv(path) as f:
        assert f.read() == "会社名\nテスト\n"
