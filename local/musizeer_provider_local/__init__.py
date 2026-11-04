"""Local storage: the library in a folder of the machine the gateway runs on."""
from __future__ import annotations

import errno
import hashlib
import logging
import os
import shutil
from pathlib import Path
from typing import Iterator

from musizeer_sdk.auth import AccountModel, AuthDefinition, AuthFlow, AuthSession
from musizeer_sdk.interfaces import PROVIDER_API_VERSION, StorageProvider, StorageStreamResult, WorkspaceFile
from musizeer_sdk.permissions import FilesystemAccess, Permissions
from musizeer_sdk.settings import ProviderSetting

logger = logging.getLogger(__name__)

_LIBRARY_SETTING = "root_dir"
# The temporary name of a file being stored is ``.<name>.part`` in its final directory: not an audio extension, so a
# music server that scans while the copy runs ignores it.
_PART_SUFFIX = ".part"
_COPY_CHUNK = 1024 * 1024


class LocalStorageProvider(StorageProvider):
    name = "local"
    label = "Local Storage"
    provider_api_version = PROVIDER_API_VERSION
    # Read and write in the one folder the user sets in `root_dir` (the library), and nowhere else: the sandbox binds
    # that folder, at the same path, when the gateway grants it. No network.
    permissions = Permissions(filesystem_from_settings=(FilesystemAccess(_LIBRARY_SETTING, "rw"),))
    # A folder of the host: nothing to log in to.
    auth = AuthDefinition(flow=AuthFlow.NONE, account_model=AccountModel.NONE)

    def config_schema(self) -> list[ProviderSetting]:
        return [
            # A folder of the machine (ADR-0008): the administrator picks one of the root folders and a path inside it,
            # and the provider receives the absolute result. There is no default root and no default path: until the
            # folder is set the host starts no download and never calls store().
            ProviderSetting(
                key=_LIBRARY_SETTING, type="folder", default=None,
                label="Library folder",
                required=False,
                description="Folder where the library files are stored.",
            ),
        ]

    def library_folder_setting(self) -> str | None:
        return _LIBRARY_SETTING

    def validate_config(self, config: dict) -> bool:
        return True

    def test_connection(self, session: AuthSession) -> str | None:
        d = self._configured_root()
        if d is None:
            return "Library folder is not set"
        if not d.is_dir():
            return f"Library folder does not exist: {d}"
        if not os.access(d, os.W_OK):
            return f"Library folder is not writable: {d}"
        return None

    # ------------------------------------------------------------------

    def _configured_root(self) -> Path | None:
        value = self.context.setting(_LIBRARY_SETTING)
        return Path(value) if value else None

    def _root(self) -> Path:
        root = self._configured_root()
        if root is None:
            raise ValueError("The library folder is not set")
        return root

    def _full(self, relative_path: str) -> Path:
        """``relative_path`` dentro la cartella della libreria. Il controllo è
        lessicale (non segue i link simbolici, che la libreria può usare di
        proposito): rifiuta solo i path assoluti o che risalgono fuori."""
        root = Path(os.path.normpath(self._root()))
        full = Path(os.path.normpath(root / relative_path))
        if full == root or not full.is_relative_to(root):
            raise ValueError(f"'{relative_path}' is outside the library folder")
        return full

    def store(self, source: WorkspaceFile, relative_dest: str, session: AuthSession) -> str:
        """The file appears under its final name all at once, or not at all (ADR-0008 §6): a music server that scans
        the library while this runs never sees half of it. On one volume that is a ``rename``. Across mounts (the
        workspace and the library are two in the sandbox) ``rename`` fails with EXDEV and the file is copied to
        ``.<name>.part`` in the destination directory, flushed to disk and renamed onto its final name, which is atomic
        inside one directory; the source goes only after that."""
        dest = self._full(relative_dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.rename(source.path, dest)
        except OSError as exc:
            if exc.errno != errno.EXDEV:
                raise
            _copy_into_place(source.path, dest)
            try:
                os.unlink(source.path)
            except OSError as unlink_error:
                # Stored: the host removes the whole workspace when the operation ends.
                logger.warning("Stored %s but could not remove the source: %s", dest, unlink_error)
        logger.debug("Stored file: %s -> %s", source.name, dest)
        return relative_dest

    def exists(self, relative_path: str, session: AuthSession) -> bool:
        return (self._full(relative_path)).exists()

    def stream(self, relative_path: str, workspace: str, session: AuthSession) -> StorageStreamResult:
        full = self._full(relative_path)
        link = Path(workspace) / full.name
        # Un hard link costa O(1) sullo stesso volume; altrimenti copia.
        try:
            os.link(full, link)
        except OSError:
            shutil.copy2(full, link)
        return StorageStreamResult(
            file=link.name,
            media_type=_guess_media_type(full),
            filename=full.name,
        )

    def delete(self, relative_path: str, session: AuthSession) -> bool:
        full = self._full(relative_path)
        if full.exists():
            full.unlink()
            logger.debug("Deleted file: %s", full)
            return True
        return False

    def size(self, relative_path: str, session: AuthSession) -> int | None:
        full = self._full(relative_path)
        try:
            return full.stat().st_size
        except OSError:
            return None

    def list_files(self, prefix: str, session: AuthSession) -> Iterator[str]:
        root = Path(os.path.normpath(self._root()))
        base = self._full(prefix) if prefix else root
        if not base.is_dir():
            raise FileNotFoundError(f"Library folder does not exist: {base}")
        return _walk(root, base)


def _part_path(dest: Path) -> Path:
    """The hidden temporary name next to ``dest`` (a very long name, which would not fit with the extra suffix, gets
    a short fixed one)."""
    name = f".{dest.name}{_PART_SUFFIX}"
    if len(name.encode()) > 255:
        name = f".{hashlib.sha256(dest.name.encode()).hexdigest()[:32]}{_PART_SUFFIX}"
    return dest.with_name(name)


def _copy_into_place(source: str, dest: Path) -> None:
    """Copy ``source`` to ``dest`` so that ``dest`` is never visible half written; the temporary file is removed if
    anything fails."""
    part = _part_path(dest)
    try:
        with open(source, "rb") as reader, open(part, "wb") as writer:
            shutil.copyfileobj(reader, writer, _COPY_CHUNK)
            writer.flush()
            os.fsync(writer.fileno())
        shutil.copystat(source, part)
        os.replace(part, dest)
    except BaseException:
        try:
            part.unlink()
        except FileNotFoundError:
            pass
        raise


def _walk(root: Path, base: Path) -> Iterator[str]:
    # I link simbolici a file sono elencati; quelli a cartelle non vengono
    # percorsi, così un link circolare non blocca la visita. Un file che
    # sta ancora arrivando (``.<nome>.part``) non c'è ancora.
    for dirpath, _dirnames, filenames in os.walk(base):
        for filename in filenames:
            if filename.startswith(".") and filename.endswith(_PART_SUFFIX):
                continue
            yield (Path(dirpath) / filename).relative_to(root).as_posix()


def _guess_media_type(path: Path) -> str:
    ext = path.suffix.lower()
    return {
        ".mp3": "audio/mpeg",
        ".flac": "audio/flac",
        ".ogg": "audio/ogg",
        ".m4a": "audio/mp4",
        ".wav": "audio/wav",
        ".opus": "audio/opus",
    }.get(ext, "application/octet-stream")
