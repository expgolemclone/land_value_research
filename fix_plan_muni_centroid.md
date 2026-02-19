# muni_centroid改善運用プラン

## 要約
- 目的は, `muni_centroid` の行を減らし, 再計算で再現できる住所データを管理すること.
- 正本は `config/address_overrides.yaml` に統一する.
- `data/output/*_output.csv` は計算結果であり, 直接編集しない.

## 目的
- 再計算時に住所補正が確実に反映される状態を作る.
- 手修正の再現性を保つ.

## 対象企業の決め方
1. `data/output/ranking_market_cap_ratio.md` を上から確認する.
2. `住所解決タグ` に `muni_centroid` を含む企業を1社選ぶ.
3. `data/output/{code}_output.csv` の `住所解決レベル=muni_centroid` 行を修正対象にする.

## 住所の登録ルール
- 事業所名一致を最優先にする.
- 一致が曖昧な行だけ, 本社住所を暫定採用する.
- 住所は可能な限り番地まで記録する.
- 出典URLを最低1件残す.

## 実施手順
1. 住所調査.
- 公式サイトの会社情報, 事業所一覧を最優先で確認する.
- 不足時のみ補助情報を使う.

2. 正本へ登録.
- 通常行は `config/address_overrides.yaml` に `証券コード -> 事業所名 -> 完全住所` を追記する.

3. 再計算.
- 例:
```bash
python run.py --price-method idw --k 3 --p 3 --allow-web-address --no-skip-processed
```
- 1社だけ再計算したい場合は, 対象1社だけ書いた入力CSVを `--input` で指定する.

4. 結果確認.
- `data/output/{code}_output.csv` で対象行の `住所取得元` が `override` か確認する.
- `住所解決レベル` が `gaiku` または `oaza_chome` に改善したか確認する.
- `東京都合計` 行の `時価総額比(実値)` 変化を確認する.

5. ランキング更新.
- 必要に応じて `python rank_market_cap_ratio.py` を実行する.
- ランキングの値が各企業CSVの `東京都合計` と一致するか確認する.

## 進捗記録テンプレート
- 対象: `証券コード / 企業名 / 事業所名`
- 登録住所: `東京都...`
- 出典URL: `https://...`
- 変更結果: `住所取得元`, `住所解決レベル`, `時価総額比(実値)` の差分

## 注意点
- `data/output/*_output.csv` の直接編集はしない.
- 合算行(例: `本社他`)は根拠が曖昧になりやすいので, 出典を必ず残す.
- 事業所名が一致しないと override が当たらないため, 事業所名の表記ゆれを確認する.

## 完了条件
- `config/address_overrides.yaml` に対象設定が追加されている.
- 再計算後CSVで対象行の `住所取得元` が `override` になっている.
- 対象企業の `muni_centroid` 行が減るか, 解像度が改善している.
