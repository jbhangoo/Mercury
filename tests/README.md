# Tests

- Server: run `test-server.bat` from the repository root, or `uv run pytest tests/server`.
- Client: run `test-client.bat` from the repository root, or `npm test` from `client/`.
- Database: run `test-database.bat` from the repository root, or `uv run python tests/database/check_database.py`. Requires a running Postgres database with PostGIS and `DATABASE_URL` configured. For scheduled runs, add `--quiet`; successful checks then produce no output, while failures write to stderr and return a nonzero exit code for a scheduler or monitor to detect.
- Utility: reserve `tests/util/` for cross-process checks such as container startup and deployment smoke tests.