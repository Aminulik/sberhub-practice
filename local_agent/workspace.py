"""Путь файла остаётся внутри workspace. .env и каталог памяти закрыты."""

from dataclasses import dataclass
import os
from pathlib import Path
import stat


MAX_FILE_BYTES = 1024 * 1024
_CLOSED_NAMES = frozenset({".env", ".chtagent"})


class FileToolError(Exception):
    """Код ошибки для модели, без содержимого файла."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Workspace:
    root: Path

    def __post_init__(self):
        root = Path(self.root).resolve(strict=True)
        if not root.is_dir():
            raise ValueError("workspace: нужен существующий каталог")
        object.__setattr__(self, "root", root)

    @classmethod
    def from_cwd(cls):
        return cls(Path.cwd())

    def destination(self, path):
        if not isinstance(path, str) or not path.strip() or "\x00" in path:
            raise FileToolError("invalid_path")
        raw = Path(path)
        # Путь вида C:foo и зарезервированные имена Windows не принимаем.
        if raw.drive and not raw.is_absolute():
            raise PermissionError("file_access_denied")
        if os.name == "nt":
            parts = raw.parts[1:] if raw.anchor else raw.parts
            if any(":" in part or Path(part).is_reserved() or
                   (part not in (".", "..") and part.rstrip(" .") != part)
                   for part in parts):
                raise PermissionError("file_access_denied")
        if any(part.casefold() in _CLOSED_NAMES for part in raw.parts):
            raise PermissionError("file_access_denied")
        candidate = raw if raw.is_absolute() else self.root / raw
        try:
            target = candidate.resolve(strict=False)
        except (OSError, RuntimeError) as error:
            raise FileToolError("invalid_path") from error
        if not target.is_relative_to(self.root):
            raise PermissionError("file_access_denied")
        relative = target.relative_to(self.root)
        if any(part.casefold() in _CLOSED_NAMES for part in relative.parts):
            raise PermissionError("file_access_denied")
        from .memory import memory_root
        store = memory_root()
        if target == store or target.is_relative_to(store):
            raise PermissionError("file_access_denied")
        return target

    def resolve(self, path, *, kind="any"):
        target = self.destination(path)
        try:
            info = target.stat()
        except FileNotFoundError as error:
            raise FileToolError("path_not_found") from error
        if stat.S_ISREG(info.st_mode):
            # Жёсткая ссылка может вести наружу, поэтому такие файлы закрыты.
            if info.st_nlink > 1:
                raise PermissionError("file_access_denied")
            actual = "file"
        elif stat.S_ISDIR(info.st_mode):
            actual = "directory"
        else:
            raise FileToolError("unsupported_file_type")
        if kind != "any" and actual != kind:
            raise FileToolError("not_a_file" if kind == "file" else "not_a_directory")
        return target

    def read_bytes(self, path):
        target = self.resolve(path, kind="file")
        with target.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            current = self.resolve(path, kind="file")
            if current != target or not os.path.samestat(opened, current.stat()):
                raise FileToolError("file_changed")
            if opened.st_size > MAX_FILE_BYTES:
                raise FileToolError("file_too_large")
            data = stream.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            raise FileToolError("file_too_large")
        if self.resolve(path, kind="file") != target:
            raise FileToolError("file_changed")
        return target, data

    def read_text(self, path):
        _, data = self.read_bytes(path)
        try:
            text = data.decode("utf-8")
        except UnicodeError as error:
            raise FileToolError("invalid_utf8") from error
        if "\x00" in text:
            raise FileToolError("binary_file")
        return text


def as_workspace(workspace):
    return workspace if isinstance(workspace, Workspace) else Workspace(Path(workspace))


def read_file(path, *, workspace):
    return as_workspace(workspace).read_text(path)
