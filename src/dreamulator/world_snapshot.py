"""Portable backups of a world directory, including its materialized results."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
import tarfile
from io import BytesIO
from pathlib import Path, PureWindowsPath
from stat import S_ISDIR, S_ISREG
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Never, Self

from dreamulator import __version__
from dreamulator.io.loader import load_world

if TYPE_CHECKING:
    from collections.abc import Callable

MANIFEST = "dreamulator-snapshot.json"
MAX_FILES = 100_000
MAX_BYTES = 16 * 1024**3
MAX_MANIFEST = 32 * 1024**2
WORLD_DIRS = {
    "layers",
    "maps",
    "branches",
    "packs",
    "canvases",
    "design-notes",
    "civmap",
    "experiments",
}


def snapshot_world_id(value: object) -> str:
    if not isinstance(value, str) or not _safe_component(value):
        raise ValueError("Invalid snapshot world ID")
    return value


def _safe_component(name: str) -> bool:
    if any(char in '<>:"/\\|?*' or not char.isprintable() for char in name):
        return False
    return (
        0 < len(name.encode("utf-8")) <= 255
        and not name.startswith(".")
        and not name.endswith((".", " "))
        and not PureWindowsPath(name).is_reserved()
    )


def _safe_entry(name: str) -> bool:
    parts = name.split("/")
    if len(parts) > 32 or not all(_safe_component(part) for part in parts):
        return False
    return (
        parts[0] in WORLD_DIRS if len(parts) > 1 else parts[0].endswith((".yaml", ".json", ".md"))
    )


class _SnapshotEntry(tarfile.TarInfo):
    @classmethod
    def frombuf(cls, buf: bytes | bytearray, encoding: str, errors: str) -> Self:
        entry = super().frombuf(buf, encoding, errors)
        if entry.type not in (tarfile.REGTYPE, tarfile.AREGTYPE) and not (
            entry.type == tarfile.XHDTYPE and 0 < entry.size <= 64 * 1024
        ):
            raise ValueError("Unsupported snapshot header")
        return entry

    def _reject_sparse(self, *_args: object) -> Never:
        raise ValueError("Sparse snapshot entries are not supported")

    _proc_gnusparse_00 = _reject_sparse
    _proc_gnusparse_01 = _reject_sparse
    _proc_gnusparse_10 = _reject_sparse


def _files(world: Path) -> dict[str, tuple[int, int, int]]:
    files: dict[str, tuple[int, int, int]] = {}
    names: set[str] = set()
    total = 0

    def walk(directory: Path) -> None:
        nonlocal total
        for path in sorted(directory.iterdir()):
            if path.name.startswith(".") or ".bak" in path.suffixes or path.name == "__pycache__":
                continue
            metadata = path.lstat()
            name = path.relative_to(world).as_posix()
            if directory == world and name not in WORLD_DIRS and not _safe_entry(name):
                continue
            if S_ISDIR(metadata.st_mode):
                if name not in WORLD_DIRS and not _safe_entry(name):
                    raise ValueError(f"Unsupported snapshot directory: {name}")
                walk(path)
                continue
            if not S_ISREG(metadata.st_mode) or not _safe_entry(name) or name.casefold() in names:
                raise ValueError(f"Unsupported snapshot entry: {name}")
            names.add(name.casefold())
            files[name] = (metadata.st_size, metadata.st_mtime_ns, metadata.st_ctime_ns)
            total += metadata.st_size
            if len(files) > MAX_FILES or total > MAX_BYTES:
                raise ValueError("World exceeds snapshot size limits")

    if world.is_symlink() or not world.is_dir():
        raise ValueError("Snapshot source must be a world directory, not a link")
    walk(world)
    if "world.yaml" not in files:
        raise FileNotFoundError("World configuration is missing")
    return files


def export_snapshot(world: Path, output: Path) -> None:
    world_id = snapshot_world_id(world.name)
    if output.resolve().is_relative_to(world.resolve()):
        raise ValueError("Choose a snapshot destination outside the world directory")
    files = _files(world)
    load_world(world)
    checksums = {}
    stream = output.open("xb")
    try:
        with stream, tarfile.open(fileobj=stream, mode="w:gz", compresslevel=3) as archive:
            for name, (size, modified, _) in files.items():
                entry = tarfile.TarInfo(f"{world_id}/{name}")
                entry.size = size
                entry.mtime = modified / 1_000_000_000
                with (world / name).open("rb") as source:
                    checksums[name] = hashlib.file_digest(source, "sha256").hexdigest()
                    source.seek(0)
                    archive.addfile(entry, source)
            if _files(world) != files:
                raise ValueError("World changed during snapshot export; retry when idle")
            manifest = json.dumps(
                {
                    "format": 1,
                    "world": world_id,
                    "dreamulatorVersion": __version__,
                    "sha256": checksums,
                }
            ).encode("utf-8")
            if len(manifest) > MAX_MANIFEST:
                raise ValueError("World snapshot manifest is too large")
            entry = tarfile.TarInfo(MANIFEST)
            entry.size = len(manifest)
            archive.addfile(entry, BytesIO(manifest))
    except BaseException:
        output.unlink(missing_ok=True)
        raise


def restore_snapshot(
    source: Path,
    worlds: Path,
    *,
    max_bytes: int = MAX_BYTES,
    max_files: int = MAX_FILES,
    validate: Callable[[Path, str], None] | None = None,
) -> Path:
    worlds.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".restore-", dir=worlds) as staging:
        staged = Path(staging)
        try:
            world_id = _restore_files(source, staged, worlds, max_bytes, max_files)
        except (EOFError, RecursionError, OverflowError, tarfile.TarError) as error:
            raise ValueError("Invalid or truncated world snapshot") from error
        if validate is not None:
            validate(staged, world_id)
        load_world(staged)
        destination = worlds / world_id
        destination.mkdir()
        try:
            for path in staged.iterdir():
                if path.name != "world.yaml":
                    path.rename(destination / path.name)
            (staged / "world.yaml").rename(destination / "world.yaml")
        except BaseException:
            shutil.rmtree(destination)
            raise
    return destination


def _restore_files(source: Path, staged: Path, worlds: Path, max_bytes: int, max_files: int) -> str:
    world_id = ""
    total = 0
    checksums: dict[str, str] = {}
    names: set[str] = set()
    manifest = None
    with (
        gzip.open(source, mode="rb") as compressed,
        tarfile.open(fileobj=compressed, mode="r|", tarinfo=_SnapshotEntry) as archive,
    ):
        for entry in archive:
            if manifest is not None or not entry.isreg() or entry.size < 0:
                raise ValueError("Unexpected snapshot entry")
            stream = archive.extractfile(entry)
            if stream is None:
                raise ValueError("Unreadable snapshot entry")
            with stream:
                if entry.name == MANIFEST:
                    if entry.size > MAX_MANIFEST:
                        raise ValueError("Snapshot manifest is too large")
                    manifest = json.loads(stream.read().decode("utf-8"))
                    if not isinstance(manifest, dict):
                        raise ValueError("Invalid world snapshot manifest")
                    continue
                root, _, name = entry.name.partition("/")
                if not world_id:
                    world_id = snapshot_world_id(root)
                    destination = worlds / world_id
                    if destination.exists() or destination.is_symlink():
                        raise FileExistsError(f"World '{world_id}' already exists")
                if root != world_id or not _safe_entry(name) or name.casefold() in names:
                    raise ValueError("Invalid or duplicate snapshot path")
                names.add(name.casefold())
                total += entry.size
                if total > max_bytes or len(names) > max_files:
                    raise ValueError("World exceeds snapshot size limits")
                path = staged / name
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("xb") as output:
                    shutil.copyfileobj(stream, output)
                with path.open("rb") as restored:
                    checksums[name] = hashlib.file_digest(restored, "sha256").hexdigest()
                os.utime(path, (entry.mtime, entry.mtime))
        remainder = compressed.read(tarfile.RECORDSIZE + 1)
        if len(remainder) > tarfile.RECORDSIZE or any(remainder):
            raise ValueError("Unexpected data after snapshot archive")
    if (
        not manifest
        or manifest.get("format") != 1
        or manifest.get("world") != world_id
        or manifest.get("sha256") != checksums
        or "world.yaml" not in checksums
    ):
        raise ValueError("Snapshot manifest or file checksums do not match")
    return world_id
