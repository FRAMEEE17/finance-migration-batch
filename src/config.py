"""Shared paths for the pipeline."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_PARQUET = REPO_ROOT / "dataset" / "journal_entries.parquet"
WAREHOUSE_DB = REPO_ROOT / "warehouse.duckdb"
