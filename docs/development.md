## Lint / Type Check

`stackchan_server/` と `example_apps/` を対象に、`uv` で Ruff と ty を実行できます。

```bash
uv sync --group dev --group example-gemini
uv run ruff check stackchan_server example_apps
uv run ty check stackchan_server example_apps
```
