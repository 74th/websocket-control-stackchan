lint:
	uv run ruff check stackchan_server example_apps
	uv run ty check stackchan_server example_apps

lint-fix:
	uv run ruff check --fix stackchan_server example_apps
	uv run ty check stackchan_server example_apps
