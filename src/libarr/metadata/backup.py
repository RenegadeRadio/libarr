"""Portable export and import of Libarr's metadata catalog.

The archive deliberately excludes credentials, users, download clients, queue
state, and API keys.  It is a catalog migration format, not a database backup.
IDs are retained so relationships and library file records remain intact.
"""

from __future__ import annotations

import json
import os
import zipfile
from collections.abc import Iterable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast

from sqlalchemy import delete, func, insert, select
from sqlalchemy.inspection import inspect
from sqlalchemy.orm import Mapper, Session

from libarr.models import (
    Author,
    Book,
    ConversionJob,
    DiscoveryList,
    DumpIsbn,
    DumpRow,
    Edition,
    File,
    HistoryEvent,
    MetadataCache,
    QueueItem,
    ReadingProgress,
    Series,
    ShelfBook,
    Subject,
)

FORMAT = "libarr-metadata"
FORMAT_VERSION = 1
ZIP_MEMBER = "metadata.json"
MAX_ARCHIVE_BYTES = 1024 * 1024 * 1024

# Dependency order for inserts. Deletes happen in reverse order.
MODELS = (
    Author,
    Series,
    Book,
    Edition,
    File,
    Subject,
    MetadataCache,
    DumpRow,
    DumpIsbn,
    DiscoveryList,
)

# These rows refer to catalog IDs but contain user or transient operational
# state, so they are intentionally not portable. An explicit replacement must
# clear them before replacing their parent rows.
DEPENDENT_STATE = (ConversionJob, QueueItem, HistoryEvent, ReadingProgress, ShelfBook)


class MetadataArchiveError(ValueError):
    """The supplied metadata archive is invalid or unsafe to import."""


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _rows(session: Session, model: type[Any]) -> list[dict[str, Any]]:
    columns = inspect(model).columns
    return [
        {column.key: _json_value(getattr(row, column.key)) for column in columns}
        for row in session.scalars(select(model)).all()
    ]


def build_export(session: Session) -> dict[str, Any]:
    """Build a JSON-compatible, deterministic catalog export."""
    return {
        "format": FORMAT,
        "version": FORMAT_VERSION,
        "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "tables": {model.__tablename__: _rows(session, model) for model in MODELS},
    }


def write_export(session: Session, output: Path, *, force: bool = False) -> dict[str, int]:
    """Atomically write JSON or ZIP based on the output suffix."""
    if output.exists() and not force:
        raise FileExistsError(f"refusing to overwrite existing file: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = build_export(session)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    try:
        if output.suffix.lower() == ".zip":
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(ZIP_MEMBER, encoded)
        else:
            temporary.write_bytes(encoded)
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    return {name: len(rows) for name, rows in payload["tables"].items()}


def _read_payload(source: Path) -> dict[str, Any]:
    if source.suffix.lower() == ".zip":
        with zipfile.ZipFile(source) as archive:
            try:
                info = archive.getinfo(ZIP_MEMBER)
            except KeyError as exc:
                raise MetadataArchiveError(f"ZIP archive is missing {ZIP_MEMBER}") from exc
            if info.file_size > MAX_ARCHIVE_BYTES:
                raise MetadataArchiveError("metadata archive exceeds the 1 GiB safety limit")
            encoded = archive.read(info)
    else:
        if source.stat().st_size > MAX_ARCHIVE_BYTES:
            raise MetadataArchiveError("metadata archive exceeds the 1 GiB safety limit")
        encoded = source.read_bytes()
    try:
        payload = json.loads(encoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MetadataArchiveError("metadata archive is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise MetadataArchiveError("metadata archive root must be an object")
    return payload


def _validate(payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    if payload.get("format") != FORMAT:
        raise MetadataArchiveError("not a Libarr metadata archive")
    if payload.get("version") != FORMAT_VERSION:
        version = payload.get("version")
        raise MetadataArchiveError(f"unsupported metadata archive version: {version}")
    tables = payload.get("tables")
    if not isinstance(tables, dict):
        raise MetadataArchiveError("metadata archive has no tables object")
    result: dict[str, list[dict[str, Any]]] = {}
    for model in MODELS:
        name = model.__tablename__
        rows = tables.get(name, [])
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise MetadataArchiveError(f"table {name} must be a list of objects")
        mapper = cast(Mapper[Any], inspect(model))
        allowed = {column.key for column in mapper.columns}
        for row in rows:
            unknown = set(row) - allowed
            if unknown:
                raise MetadataArchiveError(f"table {name} has unknown columns: {sorted(unknown)}")
        result[name] = rows
    return result


def _decode_rows(model: type[Any], rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    mapper = cast(Mapper[Any], inspect(model))
    columns = {column.key: column for column in mapper.columns}
    decoded: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        for key, value in item.items():
            if value is None:
                continue
            try:
                python_type = columns[key].type.python_type
            except NotImplementedError:
                continue
            if python_type is datetime and isinstance(value, str):
                item[key] = datetime.fromisoformat(value.removesuffix("Z"))
            elif python_type is date and isinstance(value, str):
                item[key] = date.fromisoformat(value)
        decoded.append(item)
    return decoded


def import_archive(session: Session, source: Path, *, replace: bool = False) -> dict[str, int]:
    """Import a catalog into an empty database, or replace it explicitly."""
    tables = _validate(_read_payload(source))
    populated = [
        model.__tablename__
        for model in MODELS
        if session.scalar(select(func.count()).select_from(model))
    ]
    if populated and not replace:
        raise MetadataArchiveError(
            "metadata tables are not empty; pass --replace to replace the existing catalog"
        )
    try:
        if replace:
            for dependent_model in DEPENDENT_STATE:
                session.execute(delete(dependent_model))
            for catalog_model in reversed(MODELS):
                session.execute(delete(catalog_model))
        counts: dict[str, int] = {}
        for model in MODELS:
            name = model.__tablename__
            rows = _decode_rows(model, tables[name])
            if rows:
                session.execute(insert(model), rows)
            counts[name] = len(rows)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return counts
