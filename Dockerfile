# Packaging only - no orchestration, no business logic here. Pins the
# same Python version CI and docs/runbook.md's own trap warning are
# written against (3.9's `X | None` type-hint syntax fails at import
# time; using a newer base here would hide that trap instead of
# matching what actually runs elsewhere).
FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# src/ (the pipeline), docs/ (checks.py's how_to_query_doc_has_real_trap_example
# check reads a real file under here - leaving docs/ out made that one
# check fail for a reason that had nothing to do with the pipeline,
# confirmed by actually running checks.py in the built image before
# adding this), and map_account.csv (a real, human-approved,
# version-controlled file) are baked in. dataset/, warehouse.duckdb,
# and reports/ are not - they're gitignored for the same reason they
# don't belong in an image either: dataset/ is the real 32MB extract,
# warehouse.duckdb and reports/ are rebuilt output. Mount them as
# volumes at `docker run` time instead (see README).
COPY src/ src/
COPY docs/ docs/
COPY map_account.csv .

# No ENTRYPOINT/CMD that runs the pipeline - docs/runbook.md already
# defines the run order, one script at a time. Duplicating that
# sequence into a container entrypoint would just be a second copy of
# the same logic to keep in sync. Drop into a shell instead.
CMD ["bash"]
