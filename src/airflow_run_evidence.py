"""Per-attempt run evidence for the Airflow DAG. Mission 21, issue #23.
What this records and why: docs/runbook.md's Airflow section.

Plain JSON files under reports/airflow_runs/<run_id>/<task_id>__attempt<N>.json,
never touching warehouse.duckdb. A library, not a script - used by
dags/gl_period_close.py and src/checks.py's regression tests.
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
    """Wraps one task's real body: check_inputs_unchanged() first when
    check_inputs is set, then fn(), then record_attempt() with the
    outcome - success, failed, or rejected. See the module docstring for
    which tasks should pass check_inputs and why."""
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
