"""Conversion worker (Phase 3): `ebook-convert` subprocess queue.

EPUB → AZW3 / KEPUB / PDF / MOBI per device targets. Runs `ebook-convert`
as a subprocess (GPL-clean — no Calibre code embedded), with a disk guard:
source files above a size cap are rejected without spawning the converter.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from libarr.models import ConversionJob, File

logger = logging.getLogger(__name__)

MAX_SOURCE_BYTES = 500 * 1024 * 1024  # disk guard: refuse absurd payloads


def enqueue_conversion(session: Session, file_row: File, target_format: str) -> ConversionJob:
    job = ConversionJob(file_id=file_row.id, target_format=target_format.upper())
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def _convert_one(session: Session, job: ConversionJob, out_dir: Path) -> None:
    file_row = session.get(File, job.file_id)
    if file_row is None:
        job.status = "failed"
        job.error = "source file row missing"
        return
    source = Path(file_row.path)
    if not source.is_file():
        job.status = "failed"
        job.error = f"source file not found: {source}"
        return
    if source.stat().st_size > MAX_SOURCE_BYTES:
        job.status = "failed"
        job.error = "source exceeds the disk-guard size cap"
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    job.status = "working"
    session.commit()
    try:
        if job.target_format == "KEPUB":
            # Kobo's format: kepubify subprocess (KEPUB is not plain ebook-convert).
            dest = out_dir / f"{source.stem}_converted.kepub.epub"
            command = ["kepubify", "--output-dir", str(out_dir), str(source)]
        else:
            dest = out_dir / f"{source.stem}.{job.target_format.lower()}"
            command = ["ebook-convert", str(source), str(dest)]
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
    except Exception as exc:  # noqa: BLE001 — a worker job fails, never crashes the cycle
        job.status = "failed"
        job.error = f"converter did not run: {exc}"
        session.commit()
        return

    if result.returncode != 0 or not dest.is_file():
        job.status = "failed"
        job.error = (result.stderr or result.stdout or "conversion produced no output")[:1000]
        session.commit()
        return

    job.status = "done"
    job.output_path = str(dest)
    session.commit()


def process_conversions(session: Session, *, out_dir: str = "data/converted") -> dict[str, int]:
    """Run every queued conversion job; returns {completed, failed}."""
    jobs = session.scalars(select(ConversionJob).where(ConversionJob.status == "queued")).all()
    stats = {"completed": 0, "failed": 0}
    for job in jobs:
        _convert_one(session, job, Path(out_dir))
        if job.status == "done":
            stats["completed"] += 1
        else:
            stats["failed"] += 1
            logger.warning("conversion job %s failed: %s", job.id, job.error)
    return stats
