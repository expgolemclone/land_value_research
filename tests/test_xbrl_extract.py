from __future__ import annotations

from pathlib import Path

from src.xbrl_extract import extract_facilities_from_xbrl


def _write_ixbrl(tmp_path: Path, body: str) -> Path:
    xbrl_path = tmp_path / "S100TEST"
    public_doc = xbrl_path / "XBRL" / "PublicDoc"
    public_doc.mkdir(parents=True)
    (public_doc / "0103010_honbun_test_ixbrl.htm").write_text(
        f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:ix="http://www.xbrl.org/2008/inlineXBRL">
<body>
<ix:nonNumeric name="jpcrp_cor:MajorFacilitiesTextBlock" contextRef="FilingDateInstant" escape="true">
{body}
</ix:nonNumeric>
</body>
</html>
""",
        encoding="utf-8",
    )
    return xbrl_path


def test_extracts_land_rows_from_ixbrl_table_with_rowspans(tmp_path: Path) -> None:
    xbrl_path = _write_ixbrl(
        tmp_path,
        """
<h3>２【主要な設備の状況】</h3>
<table>
<tbody>
<tr>
  <td rowspan="2">会社名</td>
  <td rowspan="2">名称（所在地）</td>
  <td rowspan="2">用途</td>
  <td rowspan="2">構造</td>
  <td rowspan="2">竣工</td>
  <td rowspan="2">建物延床面積（㎡）</td>
  <td rowspan="2">土地面積（㎡）</td>
  <td colspan="4">帳簿価額（百万円）</td>
</tr>
<tr>
  <td>建物</td><td>土地</td><td>その他</td><td>合計</td>
</tr>
<tr>
  <td>三井不動産㈱</td>
  <td>日本橋室町三井タワー<br />（東京都中央区）</td>
  <td>オフィス</td><td>RC造</td><td>2019.３</td>
  <td>※１</td><td>※１※２</td><td>72,898</td><td>108,443</td><td>3,041</td><td>184,383</td>
</tr>
<tr>
  <td></td><td></td><td></td><td></td><td></td>
  <td>151,579</td><td>10,255</td><td></td><td></td><td></td><td></td>
</tr>
</tbody>
</table>
""",
    )

    result = extract_facilities_from_xbrl(str(xbrl_path))

    assert len(result.sites) == 1
    site = result.sites[0]
    assert site.site_name == "日本橋室町三井タワー"
    assert site.location_short == "東京都中央区"
    assert site.land_area_m2 == 10_255.0
    assert site.land_book_value_yen == 108_443_000_000
    assert "主要な設備の状況" in result.section_text


def test_skips_ixbrl_rental_table_without_land_column(tmp_path: Path) -> None:
    xbrl_path = _write_ixbrl(
        tmp_path,
        """
<h3>２【主要な設備の状況】</h3>
<table>
<tbody>
<tr>
  <td rowspan="2">事業所名（所在地）</td>
  <td rowspan="2">設備の内容</td>
  <td colspan="3">帳簿価額（千円）</td>
  <td rowspan="2">従業員数（名）</td>
</tr>
<tr><td>建物</td><td>その他</td><td>合計</td></tr>
<tr>
  <td>本社<br />（東京都渋谷区）</td>
  <td>事務所用設備</td>
  <td>13,257</td><td>1,179</td><td>232,009</td><td>100</td>
</tr>
</tbody>
</table>
<p>上記の他、連結会社以外から賃借している設備があります。</p>
""",
    )

    result = extract_facilities_from_xbrl(str(xbrl_path))

    assert result.sites == []
    assert "賃借している設備" in result.section_text
