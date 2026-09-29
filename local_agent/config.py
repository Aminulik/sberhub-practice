"""Лимиты, таймауты и разрешённые инструменты в одном месте."""
from pathlib import Path

from .workspace import Workspace

CONFIG = {
    "max_steps": 8,
    "watchdog": 8,
    "model_timeout": 20.0,
    "tool_timeout": 5,
    "allowed_tools": [
        "add", "divide", "multiply", "subtraction",
        "read_file", "list_files", "replace_in_file",
        "create_file", "create_directory",
    ],
    "workspace": None,
    "log_events": True,
}


class Config:
    def __init__(self, data=None):
        object.__setattr__(self, "_data", CONFIG if data is None else data)

    def __getattr__(self, name):
        try:
            return self._data[name]
        except KeyError as error:
            raise AttributeError(name) from error

    def __setattr__(self, name, value):
        self._data[name] = value

    @classmethod
    def from_env(cls, workspace_root):
        config = cls(CONFIG)
        config.bind_workspace(workspace_root)
        return config

    def bind_workspace(self, root):
        self.workspace = Workspace(Path(root).resolve(strict=True))
        return self.workspace
