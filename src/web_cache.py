import os
import urllib.request

DEFAULT_TIMEOUT_SEC = 20


def is_pdf_file(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            head = f.read(5)
        return head == b"%PDF-"
    except OSError:
        return False


def download_file(url: str, out_path: str) -> None:
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; land_value_research/1.0)"},
    )
    with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT_SEC) as resp:
        data = resp.read()
    if not data.startswith(b"%PDF-"):
        raise ValueError(f"PDF取得に失敗しました. URLがPDF直リンクではない可能性があります: {url}")
    with open(out_path, "wb") as f:
        f.write(data)
