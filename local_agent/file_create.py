"""Новый файл не затирает существующий. Каталог можно создать вложенным."""

import os

from .file_edit import WriteGuard
from .workspace import MAX_FILE_BYTES, FileToolError, as_workspace


def _relative(scope, target):
    if target == scope.root:
        return "."
    return target.relative_to(scope.root).as_posix()


def create_file(path, content="", *, workspace, guard=None):
    if not isinstance(content, str):
        raise FileToolError("invalid_arguments")
    if "\x00" in content:
        raise FileToolError("binary_file")
    data = content.encode("utf-8")
    if len(data) > MAX_FILE_BYTES:
        raise FileToolError("file_too_large")
    scope = as_workspace(workspace)
    guard = guard or WriteGuard()
    guard.check()
    target = scope.destination(path)
    relative = _relative(scope, target)
    if target.exists():
        if not target.is_file():
            raise FileToolError("not_a_file")
        if target.stat().st_nlink > 1:
            raise PermissionError("file_access_denied")
        return {
            "created": False,
            "path": relative,
            "detail": "файл уже существует и не был перезаписан",
        }
    if not target.parent.is_dir():
        raise FileToolError("parent_not_found")
    result = {"created": True, "path": relative}

    def commit():
        guard.check()
        if target.exists():
            raise FileToolError("file_exists")
        descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
            os.write(descriptor, data)
        except Exception:
            os.close(descriptor)
            target.unlink(missing_ok=True)
            raise
        os.close(descriptor)

    try:
        return guard.commit(commit, result)
    except FileToolError as error:
        if error.code == "file_exists":
            return {
                "created": False,
                "path": relative,
                "detail": "файл уже существует и не был перезаписан",
            }
        raise


def create_directory(path, *, workspace, guard=None):
    scope = as_workspace(workspace)
    guard = guard or WriteGuard()
    guard.check()
    target = scope.destination(path)
    relative = _relative(scope, target)
    if target.exists():
        if not target.is_dir():
            raise FileToolError("not_a_directory")
        return {"created": False, "path": relative, "detail": "каталог уже существует"}
    result = {"created": True, "path": relative}

    def commit():
        guard.check()
        if target.is_dir():
            raise FileToolError("directory_exists")
        try:
            target.mkdir(parents=True, exist_ok=False)
        except FileExistsError as error:
            if target.is_dir():
                raise FileToolError("directory_exists") from error
            raise FileToolError("not_a_directory") from error
        except NotADirectoryError as error:
            raise FileToolError("not_a_directory") from error

    try:
        return guard.commit(commit, result)
    except FileToolError as error:
        if error.code == "directory_exists":
            return {"created": False, "path": relative, "detail": "каталог уже существует"}
        raise
