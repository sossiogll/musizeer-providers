"""
The local storage, against real folders.

Ported from the main repository:

- ``test_storage_listing.py`` (its local half): ``list_files`` gives the path of every file relative to the library root;
- ``test_storage_streaming.py`` (``test_local_storage_links_the_library_file_into_the_workspace``): ``stream`` puts the
  library file in the call's workspace as a hard link;
- ``test_download_to_library.py`` (``test_local_storage_uses_its_own_root_setting``): ``store``;
- ``test_library_path_safety.py`` (the two ``test_local_storage_*`` tests): a path outside the folder is refused.

"Added here" has what runs differently in a sandbox, where the library folder and the workspace are two different
mounts.
"""
from __future__ import annotations

import errno
import os
import shutil
from pathlib import Path

import pytest

from musizeer_provider_local import LocalStorageProvider
from musizeer_sdk.auth import AuthSession
from musizeer_sdk.context import StaticProviderContext
from musizeer_sdk.interfaces import WorkspaceFile


# ------------------------------------------------------------------
# test_storage_listing.py
# ------------------------------------------------------------------


@pytest.fixture
def library(tmp_path):
    root = tmp_path / "library"
    for rel in ("A/One/01 song.flac", "A/One/cover.jpg", "B/song.mp3", ".musizeer-work/x/part.flac"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(b"x")
    return root


def _local(root) -> LocalStorageProvider:
    return LocalStorageProvider(StaticProviderContext(settings={"root_dir": str(root)}, provider_name="local"))


def test_local_storage_lists_every_file_relative_to_the_library_root(library):
    files = _local(library).list_files("", session=None)

    assert sorted(files) == [
        ".musizeer-work/x/part.flac", "A/One/01 song.flac", "A/One/cover.jpg", "B/song.mp3",
    ]


def test_local_storage_lists_only_under_a_prefix(library):
    assert sorted(_local(library).list_files("A", session=None)) == ["A/One/01 song.flac", "A/One/cover.jpg"]


def test_local_storage_does_not_descend_into_a_linked_folder(library):
    os.symlink(library / "A", library / "B" / "loop")

    assert "B/loop/One/01 song.flac" not in list(_local(library).list_files("", session=None))


def test_a_missing_local_library_is_an_error_not_an_empty_library(tmp_path):
    with pytest.raises(FileNotFoundError):
        _local(tmp_path / "missing").list_files("", session=None)



# ------------------------------------------------------------------
# test_storage_streaming.py, test_download_to_library.py, test_library_path_safety.py
# ------------------------------------------------------------------


@pytest.fixture
def stocked(tmp_path):
    root = tmp_path / "library"
    (root / "A").mkdir(parents=True)
    (root / "A" / "song.flac").write_bytes(b"audio-bytes")
    return root


def test_local_storage_links_the_library_file_into_the_workspace(tmp_path, stocked):
    local = _local(stocked)
    workspace = tmp_path / "work" / "store"
    workspace.mkdir(parents=True)

    result = local.stream("A/song.flac", str(workspace), session=None)

    linked = workspace / result.file
    assert linked.read_bytes() == b"audio-bytes"
    assert os.stat(linked).st_ino == os.stat(stocked / "A" / "song.flac").st_ino  # a hard link, not a copy
    shutil.rmtree(workspace)
    assert (stocked / "A" / "song.flac").exists()  # the library is untouched


def test_local_storage_uses_its_own_root_setting(tmp_path):
    root = tmp_path / "library"
    local = _local(root)
    workspace = tmp_path / "work" / "fakedl"
    workspace.mkdir(parents=True)
    (workspace / "song.flac").write_bytes(b"audio")

    stored = local.store(WorkspaceFile(workspace=str(workspace), name="song.flac"), "A/B/Song.flac", session=None)

    assert stored == "A/B/Song.flac"
    assert (root / "A" / "B" / "Song.flac").read_bytes() == b"audio"


@pytest.mark.parametrize("relative", ["../outside.mp3", "/etc/passwd", "A/../../outside.mp3", "."])
def test_local_storage_refuses_paths_outside_its_folder(tmp_path, relative):
    storage = _local(tmp_path / "lib")

    with pytest.raises(ValueError):
        storage.exists(relative, AuthSession.anonymous())


def test_local_storage_accepts_paths_inside_its_folder(tmp_path):
    (tmp_path / "lib" / "A").mkdir(parents=True)
    (tmp_path / "lib" / "A" / "t.mp3").write_bytes(b"x")
    storage = _local(tmp_path / "lib")

    assert storage.exists("A/./t.mp3", AuthSession.anonymous())


# ------------------------------------------------------------------
# Added here
# ------------------------------------------------------------------


def _across_mounts(monkeypatch):
    """The library folder and the workspace are different mounts in the sandbox: a rename or a hard link between them
    fails with EXDEV."""
    def refuse(*args, **kwargs):
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    monkeypatch.setattr(os, "rename", refuse)
    monkeypatch.setattr(os, "link", refuse)


def test_a_file_is_stored_across_mounts_by_copy_and_leaves_the_workspace_empty(tmp_path, monkeypatch):
    _across_mounts(monkeypatch)
    workspace = tmp_path / "work"
    workspace.mkdir()
    (workspace / "song.flac").write_bytes(b"audio")

    _local(tmp_path / "library").store(WorkspaceFile(workspace=str(workspace), name="song.flac"), "A/Song.flac", session=None)

    assert (tmp_path / "library" / "A" / "Song.flac").read_bytes() == b"audio"
    assert not (workspace / "song.flac").exists()  # moved, as when it is one volume


def test_a_file_is_streamed_across_mounts_by_copy(tmp_path, stocked, monkeypatch):
    _across_mounts(monkeypatch)
    workspace = tmp_path / "work"
    workspace.mkdir()

    result = _local(stocked).stream("A/song.flac", str(workspace), session=None)

    assert (workspace / result.file).read_bytes() == b"audio-bytes"
    assert os.stat(workspace / result.file).st_ino != os.stat(stocked / "A" / "song.flac").st_ino
    assert (result.media_type, result.filename) == ("audio/flac", "song.flac")


@pytest.mark.parametrize("name, media_type", [
    ("a.mp3", "audio/mpeg"), ("a.flac", "audio/flac"), ("a.ogg", "audio/ogg"), ("a.m4a", "audio/mp4"),
    ("a.wav", "audio/wav"), ("a.opus", "audio/opus"), ("a.FLAC", "audio/flac"), ("a.xyz", "application/octet-stream"),
])
def test_the_media_type_comes_from_the_extension(tmp_path, name, media_type):
    root = tmp_path / "library"
    root.mkdir()
    (root / name).write_bytes(b"x")
    workspace = tmp_path / "work"
    workspace.mkdir()

    assert _local(root).stream(name, str(workspace), session=None).media_type == media_type


def test_exists_size_and_delete(tmp_path, stocked):
    local = _local(stocked)

    assert local.exists("A/song.flac", None) and not local.exists("A/none.flac", None)
    assert local.size("A/song.flac", None) == len(b"audio-bytes") and local.size("A/none.flac", None) is None
    assert local.delete("A/none.flac", None) is False
    assert local.delete("A/song.flac", None) is True and not (stocked / "A" / "song.flac").exists()


def test_the_connection_test_says_what_is_wrong_with_the_folder(tmp_path):
    assert _local(tmp_path).test_connection(None) is None
    assert "does not exist" in _local(tmp_path / "missing").test_connection(None)


def test_the_library_is_a_folder_setting_with_no_default_root_and_no_guessed_place():
    provider = LocalStorageProvider(StaticProviderContext())
    schema = {setting.key: setting for setting in provider.config_schema()}

    assert (schema["root_dir"].type, schema["root_dir"].default) == ("folder", None)
    assert provider.library_folder_setting() == "root_dir"
    # Until the administrator sets the folder the provider does not guess: it says it is not set.
    assert provider.test_connection(None) == "Library folder is not set"
    for call in (lambda: provider.exists("A/x.flac", None), lambda: provider.size("A/x.flac", None),
                 lambda: provider.delete("A/x.flac", None), lambda: provider.list_files("", None)):
        with pytest.raises(ValueError, match="not set"):
            call()


# ------------------------------------------------------------------
# store() is atomic (ADR-0008 §6)
# ------------------------------------------------------------------


def _workspace_with(tmp_path, data=b"audio", name="song.flac"):
    workspace = tmp_path / "work"
    workspace.mkdir(exist_ok=True)
    (workspace / name).write_bytes(data)
    return WorkspaceFile(workspace=str(workspace), name=name)


def _names(directory):
    return sorted(p.name for p in directory.iterdir())


def test_on_one_volume_the_file_is_renamed_into_place_and_nothing_is_copied(tmp_path, monkeypatch):
    def no_copy(*args, **kwargs):
        raise AssertionError("a rename was possible: no copy")

    monkeypatch.setattr(shutil, "copyfileobj", no_copy)
    source = _workspace_with(tmp_path)

    _local(tmp_path / "library").store(source, "A/Song.flac", session=None)

    assert _names(tmp_path / "library" / "A") == ["Song.flac"]
    assert not Path(source.path).exists()


def test_across_mounts_the_file_is_written_as_a_hidden_part_file_and_renamed_onto_its_final_name(tmp_path, monkeypatch):
    _across_mounts(monkeypatch)
    source = _workspace_with(tmp_path, b"audio-bytes")
    final = tmp_path / "library" / "A" / "Song.flac"
    seen = {}
    real_copy, real_fsync, real_replace = shutil.copyfileobj, os.fsync, os.replace

    def copy_then_look(reader, writer, *args):
        real_copy(reader, writer, *args)
        writer.flush()
        seen["after_copy"] = (_names(final.parent), final.exists())

    def fsync(fd):
        seen["fsync_before_replace"] = "replaced" not in seen
        real_fsync(fd)

    def replace(src, dst):
        seen["replace"] = (Path(src).name, Path(dst))
        real_replace(src, dst)
        seen["replaced"] = True

    monkeypatch.setattr(shutil, "copyfileobj", copy_then_look)
    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(os, "replace", replace)

    _local(tmp_path / "library").store(source, "A/Song.flac", session=None)

    # While the bytes are being written only the hidden temporary file exists; the final name is not there yet.
    assert seen["after_copy"] == ([".Song.flac.part"], False)
    assert seen["fsync_before_replace"] is True
    assert seen["replace"] == (".Song.flac.part", final)
    assert _names(final.parent) == ["Song.flac"] and final.read_bytes() == b"audio-bytes"
    assert not Path(source.path).exists()  # the source goes only after the final name is in place


def test_a_failed_copy_leaves_no_partial_file_and_keeps_the_source(tmp_path, monkeypatch):
    _across_mounts(monkeypatch)
    source = _workspace_with(tmp_path, b"audio")
    real_copy = shutil.copyfileobj

    def dies_halfway(reader, writer, *args):
        writer.write(b"au")
        writer.flush()
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(shutil, "copyfileobj", dies_halfway)

    with pytest.raises(OSError, match="No space"):
        _local(tmp_path / "library").store(source, "A/Song.flac", session=None)

    monkeypatch.setattr(shutil, "copyfileobj", real_copy)
    assert _names(tmp_path / "library" / "A") == []  # neither the final name nor a .part file
    assert Path(source.path).read_bytes() == b"audio"  # a retry has the file


def test_a_failed_rename_onto_the_final_name_leaves_no_partial_file_and_keeps_the_source(tmp_path, monkeypatch):
    _across_mounts(monkeypatch)
    source = _workspace_with(tmp_path)

    def refuse(*args):
        raise PermissionError(errno.EACCES, "Permission denied")

    monkeypatch.setattr(os, "replace", refuse)

    with pytest.raises(PermissionError):
        _local(tmp_path / "library").store(source, "A/Song.flac", session=None)

    assert _names(tmp_path / "library" / "A") == []
    assert Path(source.path).exists()


def test_an_error_other_than_a_cross_device_one_is_not_answered_with_a_copy(tmp_path, monkeypatch):
    def refuse(*args, **kwargs):
        raise PermissionError(errno.EACCES, "Permission denied")

    monkeypatch.setattr(os, "rename", refuse)
    source = _workspace_with(tmp_path)

    with pytest.raises(PermissionError):
        _local(tmp_path / "library").store(source, "A/Song.flac", session=None)

    assert _names(tmp_path / "library" / "A") == [] and Path(source.path).exists()


def test_across_mounts_a_file_already_in_the_library_is_replaced_without_a_moment_without_it(tmp_path, monkeypatch):
    _across_mounts(monkeypatch)
    library = tmp_path / "library"
    (library / "A").mkdir(parents=True)
    (library / "A" / "Song.flac").write_bytes(b"old")
    seen = []
    real_copy = shutil.copyfileobj

    def copy_then_look(reader, writer, *args):
        real_copy(reader, writer, *args)
        seen.append((library / "A" / "Song.flac").read_bytes())

    monkeypatch.setattr(shutil, "copyfileobj", copy_then_look)

    _local(library).store(_workspace_with(tmp_path, b"new"), "A/Song.flac", session=None)

    assert seen == [b"old"] and (library / "A" / "Song.flac").read_bytes() == b"new"


def test_across_mounts_a_name_too_long_for_the_part_suffix_still_stores(tmp_path, monkeypatch):
    _across_mounts(monkeypatch)
    name = "x" * 250 + ".flac"  # 255 bytes: the final name fits, ".<name>.part" would not
    source = _workspace_with(tmp_path, b"audio", name="in.flac")

    _local(tmp_path / "library").store(source, name, session=None)

    assert _names(tmp_path / "library") == [name]


def test_the_modification_time_survives_a_copy_across_mounts(tmp_path, monkeypatch):
    _across_mounts(monkeypatch)
    source = _workspace_with(tmp_path)
    os.utime(source.path, (1_000_000_000, 1_000_000_000))

    _local(tmp_path / "library").store(source, "A/Song.flac", session=None)

    assert int((tmp_path / "library" / "A" / "Song.flac").stat().st_mtime) == 1_000_000_000


def test_a_file_that_is_still_arriving_is_not_listed(tmp_path):
    library = tmp_path / "library"
    (library / "A").mkdir(parents=True)
    (library / "A" / "Song.flac").write_bytes(b"x")
    (library / "A" / ".Other.flac.part").write_bytes(b"xx")

    assert list(_local(library).list_files("", session=None)) == ["A/Song.flac"]


def test_the_manifest_is_a_storage_provider_without_seek_by_offset_and_with_listing():
    from musizeer_sdk.manifest import build

    manifest = build(_local("/x"))

    assert (manifest.name, manifest.label, manifest.roles) == ("local", "Local Storage", ("storage",))
    assert manifest.declarations["supports_stream_offset"] is False
    assert {"store", "exists", "stream", "delete", "size", "list_files"} <= set(manifest.implements)
