"""Per-attempt run evidence for the Airflow DAG. Mission 21, issue #23.

Records, for every task attempt: the DAG run id, task id, attempt
number, requested period, outcome, and a SHA-256 hash of the source
parquet and map_account.csv as they stood at that attempt - every task
gets this record, whether or not it reads those files itself, since the
point is a full per-run trail, not just a per-file one.

Defensive, not just informational, for the two tasks that actually
consume those files: a recovery is a clear-and-rerun inside the same
DAG run_id. Before load_stg or load_fact's real body runs,
run_with_evidence(..., check_inputs=True) compares the current
source/mapping hashes against that same run's earlier attempt of that
same task, and rejects the attempt if either changed - Airflow's retry
model assumes a task is idempotent against unchanged inputs (mission
20's own retries=1 justification), and this is what makes that
assumption checkable instead of assumed. Every other task passes
check_inputs=False (source/mapping identity has nothing to do with
whether reconcile_mismatch's retry is safe) but still gets recorded.

Plain JSON files under reports/airflow_runs/, one per attempt. Never
touches warehouse.duckdb - evidence survives independently of the
database, and reading it back doesn't require a connection.

Run: nothing to run directly - a library used by dags/gl_period_close.py
and by src/checks.py's regression tests.
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional, TypeVar

from config import REPO_ROOT, SOURCE_PARQUET
from load_fact import MAP_CSV

EVIDENCE_DIR = REPO_ROOT / "reports" / "airflow_runs"

T = TypeVar("T")


class RunEvidenceError(Exception):
    """Raised when a recovery attempt's inputs disagree with an earlier
    attempt's recorded inputs in the same DAG run."""


def sha256_file(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _run_dir(run_id: str) -> Path:
    """run_id (e.g. manual__2026-09-15T10:07:20+00:00) contains ':' and
    '+', not filesystem-safe on every platform - sanitized into the
    directory name only. The recorded evidence keeps the real run_id
    verbatim, so nothing is lost."""
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in run_id)
    return EVIDENCE_DIR / safe


def prior_attempts(run_id: str, task_id: str) -> List[dict]:
    """Sorted by the recorded `attempt` number, not file mtime - mtime
    resolution is coarse enough on some filesystems that two attempts
    written close together could sort in the wrong order, and the real
    ordering key is already in the filename and the record itself."""
    d = _run_dir(run_id)
    if not d.exists():
        return []
    return sorted(
        (json.loads(p.read_text()) for p in d.glob(f"{task_id}__attempt*.json")),
        key=lambda rec: rec["attempt"],
    )


def check_inputs_unchanged(run_id: str, task_id: str) -> None:
    prior = prior_attempts(run_id, task_id)
    if not prior:
        return  # first attempt of this task in this run - nothing to compare against
    last = prior[-1]
    source_hash = sha256_file(SOURCE_PARQUET)
    mapping_hash = sha256_file(MAP_CSV)
    if last["source_sha256"] != source_hash:
        raise RunEvidenceError(
            f"{task_id}: source file changed since attempt {last['attempt']} of run {run_id!r} "
            f"({last['source_sha256']} -> {source_hash}) - not a safe recovery, run a fresh DAG run instead"
        )
    if last["mapping_sha256"] != mapping_hash:
        raise RunEvidenceError(
            f"{task_id}: map_account.csv changed since attempt {last['attempt']} of run {run_id!r} "
            f"({last['mapping_sha256']} -> {mapping_hash}) - not a safe recovery, run a fresh DAG run instead"
        )


def record_attempt(
    run_id: str, task_id: str, attempt: int,
    company_code: int, fiscal_year: int, fiscal_period: int,
    outcome: str, detail: Optional[str] = None,
) -> Path:
    d = _run_dir(run_id)
    d.mkdir(parents=True, exist_ok=True)
    record = {
        "run_id": run_id,
        "task_id": task_id,
        "attempt": attempt,
        "company_code": company_code,
        "fiscal_year": fiscal_year,
        "fiscal_period": fiscal_period,
        "outcome": outcome,
        "detail": detail,
        "source_path": str(SOURCE_PARQUET),
        "source_sha256": sha256_file(SOURCE_PARQUET),
        "mapping_path": str(MAP_CSV),
        "mapping_sha256": sha256_file(MAP_CSV),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    out = d / f"{task_id}__attempt{attempt}.json"
    out.write_text(json.dumps(record, indent=2))
    return out


def run_with_evidence(
    run_id: str, task_id: str, attempt: int,
    company_code: int, fiscal_year: int, fiscal_period: int,
    fn: Callable[[], T],
    check_inputs: bool = True,
) -> T:
    """Wraps one task's real body. If check_inputs is set, compares this
    attempt's source/mapping hashes against any earlier attempt of the
    same task in the same run before running anything - only load_stg
    and load_fact actually read those files, so only those two tasks
    pass check_inputs=True (scrutinize finding: checking it on every
    task means a task that never reads the source can get its retry
    rejected over a file it doesn't use). Every task still records an
    attempt either way, success, failure, or a rejected recovery - the
    rejection itself used to raise before record_attempt ever ran,
    which left the one event this module exists to catch missing from
    its own evidence trail."""
    try:
        if check_inputs:
            check_inputs_unchanged(run_id, task_id)
        result = fn()
    except RunEvidenceError as e:
        record_attempt(run_id, task_id, attempt, company_code, fiscal_year, fiscal_period, "rejected", detail=str(e))
        raise
    except Exception as e:
        record_attempt(run_id, task_id, attempt, company_code, fiscal_year, fiscal_period, "failed", detail=str(e))
        raise
    record_attempt(run_id, task_id, attempt, company_code, fiscal_year, fiscal_period, "success")
    return result
