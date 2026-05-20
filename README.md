## [land_value_research](https://expgolemclone.github.io/land_value_research/docs/)

- 日本の上場企業が所有する東京の土地の含み益を求めるPipeline
- [含み益/時価総額のランキング](https://expgolemclone.github.io/land_value_research/)

---

## 実行コマンド

通常のパイプライン実行:

```bash
uv run python run.py
```

`formula_screening` の戦略結果に絞ってランキングを表示する場合:

```bash
uv run python run.py --screening-config config/screening/net_cash_fcf.toml
```

`run.py` はデフォルトで処理後にランキングWeb UIを起動する。起動しない場合は `--no-serve-ranking` を付ける。

GitHub Pages用に通常版と `net_cash_fcf` 版のJSONをまとめて更新:

```bash
uv run python -m src.web --export-github-pages
```

公開ページは通常版が `/docs/`、`net_cash_fcf` 版が `/docs/net_cash_fcf.html`。

---

> [!NOTE]
> 仕様は[ARCHITECTURE.md](ARCHITECTURE.md)を参照
