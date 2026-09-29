"""Цикл: история и вопрос -> модель -> инструменты -> ответ."""

import json
import logging
from pathlib import Path
import time
import uuid

from .config import Config
from .file_edit import WriteGuard
from .memory import load_messages, remember
from .tools import TOOL_SCHEMAS, call_tool
from .workspace import Workspace

# Журнал: запрос, ответ, инструменты и ошибки, без текста вопроса и ключа.
logger = logging.getLogger("harness")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.FileHandler("harness.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)


def log_event(**fields):
    """Записать структурированное событие в журнал."""
    logger.info(json.dumps(fields, ensure_ascii=False))


class RunResult(dict):
    @property
    def reason(self):
        return self.get("status")

    @property
    def answer(self):
        return self.get("answer")


def execute_tool(call, config):
    """Workspace и WriteGuard задаёт harness. Отмена guard останавливает позднюю запись."""
    name = call["function"]["name"]
    raw_args = call["function"]["arguments"]
    timeout = config.tool_timeout
    guard = WriteGuard(seconds=timeout)
    return call_tool(
        name, raw_args, workspace=config.workspace, guard=guard, timeout=timeout,
    )


def tool_message(call_id, result):
    """Связать строковый результат с исходным вызовом модели."""
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "content": json.dumps(result, ensure_ascii=False, allow_nan=False),
    }


def run(ask_model, question, config=None, max_steps=None):
    """Один шаг — один запрос к модели. Лимит шагов читается из конфигурации."""
    if config is None:
        config = Config()
    if not isinstance(config.workspace, Workspace):
        config.bind_workspace(Path.cwd())

    def step_limit():
        return config.max_steps if max_steps is None else max_steps

    run_id = uuid.uuid4().hex[:8]
    log_event(run_id=run_id, step=0, stage="start", status="ok")

    messages = [
        {
            "role": "system",
            "content": (
                "Ты учебный помощник. "
                "Арифметику выполняй только инструментами add, divide, multiply и subtraction. "
                "Файлы и папки смотри через list_files и read_file. "
                "Перед правкой прочитай файл, возьми из него точный фрагмент "
                "и через replace_in_file меняй только то, что попросил пользователь. "
                "Новый файл создавай через create_file и не перезаписывай существующий. "
                "Новые каталоги, включая вложенные, создавай через create_directory. "
                "Пока нужный инструмент не вернул результат, не утверждай, что файл создан, "
                "прочитан или изменён, и не выдумывай JSON результата. "
                "Корень workspace задан снаружи, не пытайся его расширить. "
                "Получив результаты, ответь по-русски. Если инструмент вернул "
                "ошибку, объясни её; не выдумывай результат вычисления или содержимое файла."
            ),
        },
        # Прошлые пары вопрос-ответ этой папки.
        *load_messages(config.workspace.root),
        {"role": "user", "content": question},
    ]
    cur_step = 0
    while True:
        # Лимит шагов: новый запрос к модели не отправляем.
        if cur_step >= step_limit():
            return RunResult(status="max_steps", answer=None)
        cur_step += 1
        log_event(run_id=run_id, step=cur_step, stage="request_sent", status="ok")
        started = time.perf_counter()
        try:
            response = ask_model(messages=messages, tools=TOOL_SCHEMAS)
        except Exception as error:
            if type(error).__name__ == "APITimeoutError":
                return RunResult(status="model_timeout", answer=None)
            raise
        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        message = response["message"]
        reason = response["finish_reason"]
        log_event(run_id=run_id, step=cur_step, stage="response_received",
                  status="ok", duration_ms=duration_ms)
        if reason not in ("stop", "tool_calls"):
            raise RuntimeError(f"Ответ модели не завершён: {reason}")
        messages.append(message)
        log_event(run_id=run_id, step=cur_step, stage="history_updated",
                  status="ok", role="assistant")
        calls = message.get("tool_calls") or []

        if not calls:
            if reason != "stop" or not isinstance(message.get("content"), str):
                raise RuntimeError("Модель не вернула ни вызовов, ни финального текста")
            remember(config.workspace.root, question, message["content"])
            return RunResult(status="ok", answer=message["content"])

        for call in calls:
            call_id = call["id"]
            tool_name = call["function"]["name"]
            log_event(run_id=run_id, step=cur_step, stage="tool_started",
                  status="ok", call_id=call_id, tool_name=tool_name)

            result = execute_tool(call, config)

            if isinstance(result, dict) and "error" in result:
                log_event(run_id=run_id, step=cur_step, stage="tool_error",
                      status="error", call_id=call_id, error=result["error"])

            messages.append(tool_message(call["id"], result))
            log_event(run_id=run_id, step=cur_step, stage="history_updated",
                  status="ok", role="tool", call_id=call_id)