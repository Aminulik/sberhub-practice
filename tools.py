"""Обычные функции, их описания для модели и проверка входных данных."""

import json
import math

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from config import CONFIG
#import time

def _numbers(a, b):
    """Проверить, что a и b — конечные числа."""
    for value in (a, b):
        if type(value) not in (int, float) or (isinstance(value, float) and not math.isfinite(value)):
            raise ValueError("a и b должны быть конечными числами")
    return a, b


def add(a, b):
    #time.sleep(2)
    a, b = _numbers(a, b)
    return a + b


def divide(a, b):
    a, b = _numbers(a, b)
    return a / b


def multiply(a, b): #cr3
    a, b = _numbers(a, b)
    return a * b


def subtraction(a, b): #cr3
    a, b = _numbers(a, b)
    return a - b

def read_file(path):  # cr6, cr7
    if not isinstance(path, str):
        raise ValueError("path должен быть строкой")

    workspace = CONFIG["workspace"].resolve()  # cr7: разрешённая папка (абсолютный путь)
    target = (workspace / path).resolve()      # cr7: нормализованный путь к файлу

    if not target.is_relative_to(workspace):   # cr7: вышли за пределы workspace
        return {"error": "path_outside_workspace"}
    if not target.is_file():                   # cr7: не файл
        return {"error": "not_a_file"}

    try:
        return target.read_text(encoding="utf-8")  # cr7: читаем нормализованный путь
    except OSError as error:
        return {"error": f"file_error: {error}"}

TOOL_REGISTRY = {"add": add, "divide": divide, "multiply": multiply,
                 "subtraction": subtraction,"read_file": read_file} #cr6 + read_file, cr3
_tool_pool = ThreadPoolExecutor(max_workers=4)  # cr4 пул для таймаута инструментов
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
        ("multiply", "Умножить a на b."), #cr3
        ("subtraction", "Вычесть b из a."), #cr3
    ]
] + [  #cr6 отдельная схема для read_file — параметр
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
]


def parse_arguments(raw):
    """JSON-строка -> словарь с двумя конечными числами; schema этого не делает."""
    if not isinstance(raw, str):
        raise ValueError("arguments должен быть JSON-строкой")
    args = json.loads(raw)
    if not isinstance(args, dict):
        raise ValueError("arguments должен быть JSON-объектом")
    return args


#cr3

def call_tool(name, raw_args):
    """Единственная точка входа для вызова инструмента."""
    if name in TOOL_REGISTRY and name not in CONFIG["allowed_tools"]:  # cr3: есть в реестре, но не разрешён
        return {"error": "not_allowed"}
    if name not in TOOL_REGISTRY:  # cr3: неизвестное имя
        return {"error": "unknown_tool"}

    tool = TOOL_REGISTRY[name]
    try:
        args = parse_arguments(raw_args)
    except ValueError:
        return {"error": "invalid_arguments"}

    import inspect  # cr3: для проверки лишних полей
    expected = set(inspect.signature(tool).parameters)  # cr3: какие ключи ждёт функция
    if set(args) - expected:  # cr3: лишние поля
        return {"error": "unexpected_fields"}

    try:
        future = _tool_pool.submit(tool, **args)  # cr4: запускаем в отдельном потоке
        result = future.result(timeout=CONFIG["tool_timeout"])  # cr4: ждём с таймаутом
    except FutureTimeout:
        return {"error": "tool_timeout"}
    except ValueError:
        return {"error": "invalid_arguments"}
    except TypeError:
        return {"error": "invalid_arguments"}
    except ZeroDivisionError:
        return {"error": "division_error"}
    if isinstance(result, float) and not math.isfinite(result):
        return {"error": "non_finite_result"}
    return result