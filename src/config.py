"""Shared paths for the pipeline."""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# GL_SOURCE_PATH overrides the source file - CI points this at
# tests/fixtures/journal_entries_ci.parquet (ticket 18), never at the
# real 32MB dataset, which stays out of git on purpose. Unset locally:
# defaults to the real file exactly as before.
SOURCE_PARQUET = Path(os.environ.get("GL_SOURCE_PATH", REPO_ROOT / "dataset" / "journal_entries.parquet"))

# Same override pattern, so a fixture run (local or CI) never lands in
# the same file as a developer's real local warehouse.
WAREHOUSE_DB = Path(os.environ.get("GL_WAREHOUSE_PATH", REPO_ROOT / "warehouse.duckdb"))
