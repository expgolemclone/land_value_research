import csv
import re
from dataclasses import dataclass
from pathlib import Path

import pdfplumber
import pypdfium2 as pdfium
from rapidocr_onnxruntime import RapidOCR

from src.config import INPUT_CSV
from src.config import PDF_CACHE_DIR as _PDF_CACHE_DIR
from src.pdf_extract import extract_major_facilities_land
from src.utils import open_csv

# 補助スクリプト: OCR検証専用. 本体処理(run.py)には必須ではない.

FW_TRANS = str.maketrans("０１２３４５６７８９，．（）－", "0123456789,.()-")
BASE_DIR = Path(__file__).resolve().parents[1]
PDF_CACHE_DIR = _PDF_CACHE_DIR


def norm(s: str) -> str:
    return re.sub(r"\s+", "", (s or "").translate(FW_TRANS))


def number_forms(v: float) -> list[str]:
    out: list[str] = []
    if abs(v - round(v)) < 1e-6:
        i = int(round(v))
        out.append(str(i))
        out.append(f"{i:,}")
    else:
        out.append(f"{v:.1f}")
        out.append(f"{v:,.1f}")
    return [norm(x) for x in out]


def contains_any(text: str, cands: list[str]) -> bool:
    return any(c in text for c in cands)


def location_hint(location_short: str) -> tuple[str, str]:
    loc = norm(location_short)
    pref = ""
    city_head = ""
    if loc.startswith("東京都"):
        pref = "東京"
        tail = loc[len("東京都") :]
        city_head = tail[:1] if tail else ""
    return pref, city_head


def read_codes(path: Path) -> list[str]:
    with open_csv(path) as f:
        return [
            code
            for row in csv.reader(f)
            if row and (code := (row[0] or "").strip()) and code != "code"
        ]


def resolve_pdf_path(code: str) -> Path:
    PDF_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return PDF_CACHE_DIR / f"{code}_securities_report.pdf"


@dataclass
class CheckResult:
    code: str
    site_name: str
    page_no: int
    ok_loc: bool
    ok_area: bool
    ok_land: bool

    @property
    def ok(self) -> bool:
        return self.ok_loc and self.ok_area and self.ok_land


def main() -> None:
    engine = RapidOCR()
    input_path = INPUT_CSV
    codes = read_codes(input_path)
    all_results: list[CheckResult] = []

    for code in codes:
        pdf_path = resolve_pdf_path(code)
        if not pdf_path.exists():
            continue
        sites = [s for s in extract_major_facilities_land(str(pdf_path)) if s.location_short.startswith("東京都")]
        if not sites:
            continue

        with pdfplumber.open(str(pdf_path)) as pdf:
            page_texts = [norm(p.extract_text() or "") for p in pdf.pages]

        doc = pdfium.PdfDocument(str(pdf_path))

        ocr_cache: dict[int, str] = {}

        def ocr_page(i: int) -> str:
            if i not in ocr_cache:
                img = doc[i].render(scale=2).to_numpy()
                res, _ = engine(img)
                text = ""
                if res:
                    text = "".join(norm(r[1]) for r in res if r[2] >= 0.55)
                ocr_cache[i] = text
            return ocr_cache[i]

        for s in sites:
            loc_token = norm(s.location_short)
            page_idx = 0
            land_src = s.land_book_value_yen
            area_src = s.land_area_m2

            best_score = -1
            for i, txt in enumerate(page_texts):
                is_thousand_yen = ("帳簿価額(千円)" in txt) or ("帳簿価額（千円）" in txt)
                is_thousand_m2 = ("千㎡" in txt) or ("(千m2)" in txt)
                cand_land = s.land_book_value_yen / (1_000 if is_thousand_yen else 1_000_000)
                cand_area = s.land_area_m2 / (1_000.0 if is_thousand_m2 else 1.0)

                score = 0
                if loc_token and loc_token in txt:
                    score += 1
                if contains_any(txt, number_forms(cand_area)):
                    score += 1
                if contains_any(txt, number_forms(cand_land)):
                    score += 1
                if score > best_score:
                    best_score = score
                    page_idx = i
                    land_src = cand_land
                    area_src = cand_area

            ocr_txt = ocr_page(page_idx)
            pref, city_head = location_hint(s.location_short)
            res = CheckResult(
                code=code,
                site_name=s.site_name,
                page_no=page_idx + 1,
                ok_loc=((pref in ocr_txt) and (city_head in ocr_txt)),
                ok_area=contains_any(ocr_txt, number_forms(area_src)),
                ok_land=contains_any(ocr_txt, number_forms(land_src)),
            )
            all_results.append(res)

    if not all_results:
        print("TOKYO_ROWS=0")
        print("ACCURACY=100.00%")
        return

    ok_rows = sum(1 for r in all_results if r.ok)
    total_rows = len(all_results)
    acc = ok_rows / total_rows * 100.0

    for r in all_results:
        print(
            f"{r.code},{r.site_name},page={r.page_no},"
            f"loc={int(r.ok_loc)},area={int(r.ok_area)},land={int(r.ok_land)},ok={int(r.ok)}"
        )
    print(f"TOKYO_ROWS={total_rows}")
    print(f"OK_ROWS={ok_rows}")
    print(f"ACCURACY={acc:.2f}%")


if __name__ == "__main__":
    main()
