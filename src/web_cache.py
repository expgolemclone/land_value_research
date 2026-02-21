import os
import urllib.request

from src.network import urlopen_with_retry
from src.utils import validate_url_not_private

DEFAULT_TIMEOUT_SEC = 20


def is_pdf_file(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            head = f.read(5)
        return head == b"%PDF-"
    except OSError:
        return False


def download_file(url: str, out_path: str) -> None:
    validate_url_not_private(url)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; land_value_research/1.0)"},
    )
    data = urlopen_with_retry(req, timeout_sec=DEFAULT_TIMEOUT_SEC)
    if not data.startswith(b"%PDF-"):
        raise ValueError(f"PDF取得に失敗しました. URLがPDF直リンクではない可能性があります: {url}")
    with open(out_path, "wb") as f:
        f.write(data)
