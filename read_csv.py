import polars as pl # type: ignore
import os

df = pl.read_csv("hf://datasets/VynFi/vynfi-sap-showcase/journal_entries.csv", schema_overrides={"exchange_rate": pl.Float64})
output_dir = "dataset"

os.makedirs(output_dir, exist_ok=True)
df.write_csv(f"{output_dir}/journal_entries_saved.csv")
df.write_parquet(f"{output_dir}/journal_entries.parquet")
