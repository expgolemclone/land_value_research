from __future__ import annotations

import hashlib

JsonDict = dict[str, object]


def file_md5(path: str) -> str:
    """ファイルの MD5 ハッシュを返す."""
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def combined_md5(*paths: str) -> str:
    """複数ファイルの MD5 を結合して単一ハッシュを生成."""
    h = hashlib.md5()
    for p in sorted(paths):
        h.update(file_md5(p).encode())
    return h.hexdigest()


def string_md5(s: str) -> str:
    """文字列の MD5 ハッシュを返す（キャッシュキー用）."""
    return hashlib.md5(s.encode("utf-8")).hexdigest()
