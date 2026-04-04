"""Regression tests for PDF extraction helpers."""

from __future__ import annotations

import unittest

from src import pdf_extract


class TestExtractLocation(unittest.TestCase):
    def test_detects_hoka_after_closing_paren(self) -> None:
        loc, has_hoka = pdf_extract._extract_location("東京支店(東京都千代田区)他60営業所等")
        self.assertEqual(loc, "東京都千代田区")
        self.assertTrue(has_hoka)

    def test_no_false_positive_without_hoka(self) -> None:
        loc, has_hoka = pdf_extract._extract_location("本社(東京都千代田区丸の内一丁目4番1号)")
        self.assertEqual(loc, "東京都千代田区")
        self.assertFalse(has_hoka)


class TestExtractFromTable(unittest.TestCase):
    def test_skips_rental_table_without_land_column(self) -> None:
        table = [
            ["事業所名", "設備の内容", "床面積(㎡)", "年間賃借料(千円)"],
            ["(所在地)", "", "", ""],
            ["本社", "本社機能", "908.82", "86,008"],
            ["(東京都渋谷区)", "営業拠点", "", ""],
        ]

        rows, errs = pdf_extract._extract_from_table(table)

        self.assertEqual(rows, [])
        self.assertEqual(errs, [])

    def test_skips_table_without_land_column_even_if_numeric_parens_exist(self) -> None:
        table = [
            ["事業所名", "設備の内容", "合計", "従業員数"],
            ["(所在地)", "", "(千円)", "(名)"],
            ["本社\n(東京都渋谷区)", "事務所用設備", "232,009", "100(8)"],
        ]

        rows, errs = pdf_extract._extract_from_table(table)

        self.assertEqual(rows, [])
        self.assertEqual(errs, [])

    def test_extracts_land_row_with_explicit_land_column(self) -> None:
        table = [
            ["事業所名", "設備の内容", "土地", "合計"],
            ["(所在地)", "", "(百万円)(面積㎡)", "(百万円)"],
            ["本社\n(東京都江東区)", "その他設備", "407(190.1)", "680"],
        ]

        rows, errs = pdf_extract._extract_from_table(table)

        self.assertEqual(errs, [])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].site_name, "本社")
        self.assertEqual(rows[0].location_short, "東京都江東区")
        self.assertAlmostEqual(rows[0].land_area_m2, 190.1)
        self.assertEqual(rows[0].land_book_value_yen, 407_000_000)

    # --- 不動産会社形式: 名称/所在地別列 (8802 三菱地所) ---

    def test_8802_format_separate_name_and_location(self) -> None:
        """8802形式: 名称/所在地が別列, 土地グループ内に面積/帳簿価額."""
        table = [
            ["名称", "所在地", "建物", None, None, None, "土地", None, "その他", "合計"],
            [None, None, "規模", "延面積\n（㎡）", "帳簿価額\n（百万円）", "竣工", "面積\n（㎡）", "帳簿価額\n（百万円）", "帳簿価額\n（百万円）", "帳簿価額\n（百万円）"],
            ["山王パークタワー", "東京都千代田区", "地上44階\n地下 4階", "132,504", "21,004", "2000年", "12,980", "132,222", "1,618", "154,844"],
            ["新青山ビル", "東京都港区", "地上23階\n地下 4階", "98,971", "7,908", "1978年", "9,903", "25,043", "712", "33,665"],
        ]

        rows, errs = pdf_extract._extract_from_table(table)

        self.assertEqual(errs, [])
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].site_name, "山王パークタワー")
        self.assertEqual(rows[0].location_short, "東京都千代田区")
        self.assertAlmostEqual(rows[0].land_area_m2, 12_980.0)
        self.assertEqual(rows[0].land_book_value_yen, 132_222_000_000)
        self.assertEqual(rows[1].location_short, "東京都港区")

    # --- 不動産会社形式: 帳簿価額グループ内に土地 (3289 東急不動産HD) ---

    def test_3289_format_book_value_group_with_land_sub(self) -> None:
        """3289形式: 帳簿価額グループの中に土地サブ列."""
        table = [
            ["会社名", "設備の名称", "所在地", "セグメント\nの名称", "設備の内容・\n用途", "土地面積\n（㎡）", "帳簿価額（百万円）", None, None, None],
            [None, None, None, None, None, None, "土地", "建物", "その他", "合計"],
            ["東急不動産㈱", "Shibuya Sakura\nStage", "東京都渋谷区", "都市開発", "事務所・店\n舗・ホテル", "16,970", "72,118", "32,636", "2,267", "107,022"],
        ]

        rows, errs = pdf_extract._extract_from_table(table)

        self.assertEqual(errs, [])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].site_name, "Shibuya SakuraStage")
        self.assertEqual(rows[0].location_short, "東京都渋谷区")
        self.assertAlmostEqual(rows[0].land_area_m2, 16_970.0)
        self.assertEqual(rows[0].land_book_value_yen, 72_118_000_000)

    # --- 不動産会社形式: 名称（所在地）一体型 (8801 三井不動産) ---

    def test_8801_format_name_with_embedded_location(self) -> None:
        """8801形式: 名称（所在地）が1列, 土地面積と帳簿価額土地が別列."""
        table = [
            ["会社名", "名称（所在地）", "用途", "主たる構造および規模", "竣工又は\n取得年月", "建物延床面\n積（㎡）", "土地面積\n（㎡）", "帳簿価額（百万円）", None, None, None],
            [None, None, None, None, None, None, None, "建物", "土地", "その他", "合計"],
            ["三井不動産㈱", "神保町三井ビルディング\n（東京都千代田区）", "オフィス", "鉄骨造", "2003.３", "14,182", "1,292", "3,045", "8,481", "34", "11,561"],
        ]

        rows, errs = pdf_extract._extract_from_table(table)

        self.assertEqual(errs, [])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].site_name, "神保町三井ビルディング")
        self.assertEqual(rows[0].location_short, "東京都千代田区")
        self.assertAlmostEqual(rows[0].land_area_m2, 1_292.0)
        self.assertEqual(rows[0].land_book_value_yen, 8_481_000_000)

    # --- 子会社テーブル: 会社名+名称+所在地 (8802 子会社) ---

    def test_subsidiary_table_with_company_name_col(self) -> None:
        """8802子会社形式: 会社名がcol[0], 名称がcol[1], 所在地がcol[2]."""
        table = [
            ["会社名", "名称", "所在地", "建物", None, None, "土地", None, "その他", "合計"],
            [None, None, None, "規模", "延面積\n（㎡）", "帳簿価額\n（百万\n円）", "面積\n（㎡）", "帳簿価額\n（百万\n円）", "帳簿価額\n（百万\n円）", "帳簿価額\n（百万\n円）"],
            ["㈱サンシャインシティ", "サンシャインシティ", "東京都\n豊島区", "地上60階\n地下 5階", "510,042", "60,224", "55,719", "104,007", "3,692", "167,924"],
        ]

        rows, errs = pdf_extract._extract_from_table(table)

        self.assertEqual(errs, [])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].site_name, "サンシャインシティ")
        self.assertEqual(rows[0].location_short, "東京都豊島区")
        self.assertAlmostEqual(rows[0].land_area_m2, 55_719.0)
        self.assertEqual(rows[0].land_book_value_yen, 104_007_000_000)

    # --- 面積グループ内に土地サブ列 (8830 住友不動産) ---

    def test_8830_format_area_group_with_land_sub(self) -> None:
        """8830形式: 面積(㎡)グループの中に土地サブ列, 帳簿価額グループに土地等サブ列."""
        table = [
            ["会社名", "物件名称", None, "所在地", "構造", "面積(㎡)", None, "帳簿価額(百万円)", None, None, "建築年月"],
            [None, None, None, None, None, "建物", "土地", "建物等", "土地等", "合計", None],
            ["住友不動産㈱", "泉ガーデン＊", "5", "東京都\n港区", "地上43階\n地下4階", "184,033", "19,547", "23,269", "90,613", "113,883", "2002/10"],
        ]

        rows, errs = pdf_extract._extract_from_table(table)

        self.assertEqual(errs, [])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].site_name, "泉ガーデン＊")
        self.assertEqual(rows[0].location_short, "東京都港区")
        self.assertAlmostEqual(rows[0].land_area_m2, 19_547.0)
        self.assertEqual(rows[0].land_book_value_yen, 90_613_000_000)

    # --- セクションヘッダー行のスキップ ---

    def test_skips_section_header_rows(self) -> None:
        """"① 賃貸用建物等" のようなセクションヘッダー行を無視する."""
        table = [
            ["会社名", "名称（所在地）", "用途", "構造", "竣工", "建物延床面\n積（㎡）", "土地面積\n（㎡）", "帳簿価額（百万円）", None, None, None],
            [None, None, None, None, None, None, None, "建物", "土地", "その他", "合計"],
            ["① 賃貸用建物等", None, None, None, None, "", None, None, None, None, None],
            ["三井不動産㈱", "綱町三井倶楽部\n（東京都港区）", "迎賓館", "...", "1913", "5,427", "28,563", "1,099", "23,571", "500", "25,171"],
        ]

        rows, errs = pdf_extract._extract_from_table(table)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].site_name, "綱町三井倶楽部")

    # --- 注記マーカー付き面積の正しいパース ---

    def test_parses_area_with_annotation_markers(self) -> None:
        """※1※2 付き面積セルから正しい面積を抽出する."""
        table = [
            ["会社名", "名称（所在地）", "用途", "構造", "竣工", "建物延床面\n積（㎡）", "土地面積\n（㎡）", "帳簿価額（百万円）", None, None, None],
            [None, None, None, None, None, None, None, "建物", "土地", "その他", "合計"],
            ["三井不動産㈱", "日本橋室町三井タワー\n（東京都中央区）", "オフィス", "RC造", "2019.３", "※１\n151,579", "※１※２\n10,255", "72,898", "108,443", "3,041", "184,383"],
        ]

        rows, errs = pdf_extract._extract_from_table(table)

        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0].land_area_m2, 10_255.0)
        self.assertEqual(rows[0].land_book_value_yen, 108_443_000_000)

    # --- 除外テーブル ---

    def test_skips_employee_table(self) -> None:
        """従業員テーブル（土地列なし）を正しくスキップ."""
        table = [
            ["事業所名", "所在地", "セグメントの名称", "従業員数（人）"],
            ["本店", "東京都千代田区", "コマーシャル不動産事業", "1,100"],
        ]

        rows, errs = pdf_extract._extract_from_table(table)
        self.assertEqual(rows, [])

    def test_skips_equipment_plan_table(self) -> None:
        """設備計画テーブル（土地列なし）を正しくスキップ."""
        table = [
            ["会社名", "設備の名称", "所在地", "規模", "投資予定金額", None],
            [None, None, None, None, "総額\n（百万円）", "既支払額\n（百万円）"],
            ["当社", "(仮称)赤坂計画", "東京都港区", "地上40階", "未定", "6,135"],
        ]

        rows, errs = pdf_extract._extract_from_table(table)
        self.assertEqual(rows, [])

    def test_skips_lease_table(self) -> None:
        """賃借設備テーブル（土地列なし）を正しくスキップ."""
        table = [
            ["会社名", "名称", "所在地", "賃借面積(㎡)"],
            ["東急住宅リース㈱", "アーバンドエル庄内通", "愛知県名古屋市", "14,475"],
        ]

        rows, errs = pdf_extract._extract_from_table(table)
        self.assertEqual(rows, [])
