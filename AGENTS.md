read README.md

- 時価総額は `input.csv` の `market_cap` または `stock_db` の `stocks.shares_outstanding * prices.close` を使うこと.
- 時価総額の取得元として IRBank / Kabutan を追加しないこと.
- `company_metadata` に `address_source_urls` は保存しないこと. 住所調査の source URL は実行時に `input.csv` と `securities_report_pdf_url` から組み立てること.
