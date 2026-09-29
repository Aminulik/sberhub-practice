"""Арифметика и файловые инструменты. Модель вызывает их только через call_tool."""

import inspect
import json
import math

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

from .config import CONFIG
from .file_browser import list_files
from .file_create import create_directory, create_file
from .file_edit import replace_in_file
from .workspace import FileToolError
from .workspace import read_file as read_workspace_file

def _numbers(a, b):
    """Проверить, что a и b — конечные числа."""
    for value in (a, b):
        if type(value) not in (int, float) or (isinstance(value, float) and not math.isfinite(value)):
            raise ValueError("a и b должны быть конечными числами")
    return a, b


def add(a, b):
    a, b = _numbers(a, b)
    return a + b


def divide(a, b):
    a, b = _numbers(a, b)
    return a / b


def multiply(a, b):
    a, b = _numbers(a, b)
    return a * b


def subtraction(a, b):
    a, b = _numbers(a, b)
    return a - b

def read_file(path, *, workspace):
    return read_workspace_file(path, workspace=workspace)

TOOL_REGISTRY = {
    "add": add,
    "divide": divide,
    "multiply": multiply,
    "subtraction": subtraction,
    "read_file": read_file,
    "list_files": list_files,
    "replace_in_file": replace_in_file,
    "create_file": create_file,
    "create_directory": create_directory,
}
# Таймаут инструмента: ждём результат в отдельном потоке.
_tool_pool = ThreadPoolExecutor(max_workers=4)
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {
                    "a": {"type": "number", "description": "Первое число"},
                    "b": {"type": "number", "description": "Второе число"},
                },
                "required": ["a", "b"],
                "additionalProperties": False,
            },
        },
    }
    for name, description in [
        ("add", "Сложить два числа a и b."),
        ("divide", "Разделить a на b. При b=0 инструмент выдаёт ошибку."),
        ("multiply", "Умножить a на b."),
        ("subtraction", "Вычесть b из a."),
    ]
] + [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Прочитать текстовый файл по пути path и вернуть его содержимое.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Путь к файлу"},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": (
                "Показать файлы и папки внутри workspace. "
                "recursive=true обходит вложенные каталоги. "
                "Если truncated=true, список обрезан параметром limit."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Папка относительно корня workspace"},
                    "recursive": {"type": "boolean", "description": "Обойти подкаталоги"},
                    "limit": {"type": "integer", "description": "Сколько имён вернуть, от 1 до 2000"},
                },
                "required": [],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "replace_in_file",
            "description": (
                "Заменить в файле фрагмент old_text на new_text. "
                "old_text должен встречаться ровно один раз. Перед вызовом прочитай файл."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Путь к файлу внутри workspace"},
                    "old_text": {"type": "string", "description": "Точный фрагмент, который нужно заменить"},
                    "new_text": {"type": "string", "description": "Новый текст вместо этого фрагмента"},
                },
                "required": ["path", "old_text", "new_text"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_file",
            "description": (
                "Создать новый текстовый файл внутри workspace. "
                "Существующий файл не перезаписывается. content — начальный текст, можно пустой."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Путь к новому файлу внутри workspace"},
                    "content": {"type": "string", "description": "Начальное содержимое файла"},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_directory",
            "description": (
                "Создать каталог внутри workspace, в том числе вложенный. "
                "Если каталог уже есть, он не изменяется и результат это объясняет."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Путь каталога, можно с вложенными частями"},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
]


def parse_arguments(raw):
    """JSON-строка аргументов -> словарь."""
    if not isinstance(raw, str):
        raise ValueError("arguments должен быть JSON-строкой")
    args = json.loads(raw)
    if not isinstance(args, dict):
        raise ValueError("arguments должен быть JSON-объектом")
    return args


# workspace и guard подставляет harness, модель их не передаёт.
_HIDDEN_FIELDS = {"workspace", "guard"}


def call_tool(name, raw_args, *, workspace=None, guard=None, timeout=None):
    """Проверяет доступ, аргументы и таймаут, затем вызывает инструмент."""
    if name in TOOL_REGISTRY and name not in CONFIG["allowed_tools"]:
        return {"error": "not_allowed"}
    if name not in TOOL_REGISTRY:
        return {"error": "unknown_tool"}

    tool = TOOL_REGISTRY[name]
    try:
        args = parse_arguments(raw_args)
    except ValueError:
        return {"error": "invalid_arguments"}

    expected = set(inspect.signature(tool).parameters)
    if _HIDDEN_FIELDS & set(args) or set(args) - expected:
        return {"error": "unexpected_fields"}
    if "workspace" in expected:
        if workspace is None:
            return {"error": "invalid_arguments"}
        args["workspace"] = workspace
    if "guard" in expected and guard is not None:
        args["guard"] = guard

    if timeout is None:
        timeout = CONFIG["tool_timeout"]
    try:
        future = _tool_pool.submit(tool, **args)
        result = future.result(timeout=timeout)
    except FutureTimeout:
        finished = guard.cancel() if guard is not None else None
        if finished is not None:
            return finished
        return {"error": "tool_timeout"}
    except FileToolError as error:
        return {"error": error.code}
    except PermissionError as error:
        code = error.args[0] if error.args and isinstance(error.args[0], str) else "file_access_denied"
        return {"error": code}
    except ValueError:
        return {"error": "invalid_arguments"}
    except TypeError:
        return {"error": "invalid_arguments"}
    except ZeroDivisionError:
        return {"error": "division_error"}
    if isinstance(result, float) and not math.isfinite(result):
        return {"error": "non_finite_result"}
    return result