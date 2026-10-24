"""Content-addressed snapshots of project files. Does not write source files."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

_TS = "%Y-%m-%dT%H:%M:%S.%fZ"


class SnapshotError(Exception):
    """A path escapes the project, or a version id is unknown."""


@dataclass(frozen=True)
class Version:
    """One snapshot or draft. ``id`` is the manifest hash."""

    id: str
    timestamp: str
    author: str
    description: str
    paths: tuple[str, ...]


def _canonical(obj: object) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _check_path(path: str) -> str:
    if not path or path.startswith(("/", "\\")) or "\\" in path:
        raise SnapshotError("path escapes the project")
    parts = path.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise SnapshotError("path escapes the project")
    if ".iterthink" in parts:
        chat = parts[:2] == [".iterthink", "chats"] and len(parts) == 3
        if not chat or not parts[2].endswith(".md"):
            raise SnapshotError("path escapes the project")
    return path


def _atomic(directory: Path, name: str, data: bytes) -> None:
    """Write ``data`` to ``directory/name`` via a temp file, fsync, then replace."""
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / name
    if target.exists():
        return
    temporary = directory / f".{name}.{threading.get_ident()}.tmp"
    with temporary.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(target)


class Snapshots:
    """Versions under ``<project>/.iterthink/versions/``."""

    def __init__(self, project_dir: Path) -> None:
        self._root = project_dir

    def init(self) -> None:
        """Create the object and snapshot directories. Safe to call twice."""
        self._objects.mkdir(parents=True, exist_ok=True)
        self._manifests.mkdir(parents=True, exist_ok=True)

    def snapshot(self, files: dict[str, bytes], description: str, author: str) -> Version | None:
        """Store ``files`` as a new version. ``None`` when the tree matches head."""
        hashes = self._hash_files(files)
        current = self._head_manifest()
        if current is not None and current["files"] == hashes:
            return None
        parent = None if current is None else str(current["id"])
        return self._commit(hashes, description, author, parent, draft=False)

    def history(self, path: str | None = None) -> list[Version]:
        """Newest version first. ``path`` keeps versions that contain that file."""
        chosen = None if path is None else _check_path(path)
        versions = [self._version(item) for item in self._manifests_data()]
        if chosen is not None:
            versions = [item for item in versions if chosen in item.paths]
        versions.sort(key=lambda item: item.timestamp, reverse=True)
        return versions

    def file_at(self, version: str, path: str) -> bytes | None:
        """Bytes of ``path`` in ``version``, or ``None`` when the version lacks it."""
        checked = _check_path(path)
        digest = self._load(version)["files"].get(checked)
        if not isinstance(digest, str):
            return None
        return (self._objects / digest).read_bytes()

    def restore(self, version: str, paths: list[str], description: str, author: str) -> Version:
        """New version: listed paths from ``version``, every other path from head."""
        old = self._load(version)
        current = self._require_head()
        merged = dict(current["files"])
        for path in paths:
            checked = _check_path(path)
            if checked not in old["files"]:
                raise SnapshotError("path is not in that version")
            merged[checked] = old["files"][checked]
        return self._commit(merged, description, author, str(current["id"]), draft=False)

    def head(self) -> Version:
        """Latest version that is not a draft."""
        return self._version(self._require_head())

    def draft(
        self, baseline: str, changes: dict[str, bytes], description: str, author: str
    ) -> Version:
        """Store proposal bytes. Does not change head or source files."""
        self._load(baseline)
        return self._commit(self._hash_files(changes), description, author, baseline, draft=True)

    def read_draft(self, version: str) -> dict[str, bytes]:
        """Bytes proposed by a draft."""
        manifest = self._load(version)
        if manifest.get("draft") is not True:
            raise SnapshotError("not a draft")
        found: dict[str, bytes] = {}
        for path, digest in manifest["files"].items():
            if isinstance(digest, str):
                found[str(path)] = (self._objects / digest).read_bytes()
        return found

    @property
    def _objects(self) -> Path:
        return self._root / ".iterthink" / "versions" / "objects"

    @property
    def _manifests(self) -> Path:
        return self._root / ".iterthink" / "versions" / "snapshots"

    def _hash_files(self, files: Mapping[str, bytes]) -> dict[str, str]:
        hashed: dict[str, str] = {}
        for path, data in files.items():
            checked = _check_path(path)
            hashed[checked] = self._store(data)
        return hashed

    def _store(self, data: bytes) -> str:
        digest = hashlib.sha256(data).hexdigest()
        _atomic(self._objects, digest, data)
        return digest

    def _manifests_data(self) -> list[dict[str, Any]]:
        if not self._manifests.is_dir():
            return []
        found: list[dict[str, Any]] = []
        for path in sorted(self._manifests.glob("*.json")):
            found.append(self._read_manifest(path))
        return found

    def _read_manifest(self, path: Path) -> dict[str, Any]:
        parsed: object = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(parsed, dict):
            raise SnapshotError("snapshot is not an object")
        manifest = cast(dict[str, Any], parsed)
        claimed = manifest.get("id")
        if path.stem != claimed or not isinstance(claimed, str):
            raise SnapshotError("snapshot id mismatch")
        checking = dict(manifest)
        checking["id"] = ""
        digest = hashlib.sha256(_canonical(checking).encode("utf-8")).hexdigest()
        if digest != claimed:
            raise SnapshotError("snapshot id mismatch")
        files = manifest.get("files")
        if not isinstance(files, dict):
            raise SnapshotError("snapshot files are missing")
        return manifest

    def _load(self, version: str) -> dict[str, Any]:
        path = self._manifests / f"{version}.json"
        if not path.is_file():
            raise SnapshotError("unknown version")
        return self._read_manifest(path)

    def _head_manifest(self) -> dict[str, Any] | None:
        applied = [item for item in self._manifests_data() if item.get("draft") is not True]
        if not applied:
            return None
        applied.sort(key=lambda item: str(item["ts"]), reverse=True)
        return applied[0]

    def _require_head(self) -> dict[str, Any]:
        current = self._head_manifest()
        if current is None:
            raise SnapshotError("no version yet")
        return current

    def _next_ts(self) -> str:
        stamps = [str(item["ts"]) for item in self._manifests_data()]
        previous = max(stamps) if stamps else None
        stamp = datetime.now(UTC).strftime(_TS)
        if previous is not None and stamp <= previous:
            base = datetime.strptime(previous, _TS).replace(tzinfo=UTC)
            stamp = (base + timedelta(microseconds=1)).strftime(_TS)
        return stamp

    def _commit(
        self,
        files: dict[str, str],
        description: str,
        author: str,
        parent: str | None,
        *,
        draft: bool,
    ) -> Version:
        body: dict[str, Any] = {
            "author": author,
            "description": description,
            "files": files,
            "id": "",
            "parent": parent,
            "ts": self._next_ts(),
        }
        if draft:
            body["draft"] = True
        body["id"] = hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()
        _atomic(self._manifests, f"{body['id']}.json", (_canonical(body) + "\n").encode("utf-8"))
        return self._version(body)

    def _version(self, manifest: Mapping[str, Any]) -> Version:
        files = manifest["files"]
        paths = tuple(sorted(str(path) for path in files)) if isinstance(files, dict) else ()
        return Version(
            id=str(manifest["id"]),
            timestamp=str(manifest["ts"]),
            author=str(manifest["author"]),
            description=str(manifest["description"]),
            paths=paths,
        )
