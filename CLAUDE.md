1. nix-osとwindowsの両方で実行可能なスクリプトにすること.
2. `nix develop --command land-value-run --input config/input_full.csv --workers 100`

## トラブルシューティング

### Permission denied でビルドが失敗する場合

`.venv/` や `target/` 配下のファイルが root 所有になっていてビルドが失敗することがある。以下で修正:

```bash
sudo chown -R exp:users .venv/ target/
```
