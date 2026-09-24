"""Базовый синхронный harness: messages -> model -> tools -> messages."""

import json
import math
import logging #cr2
import time #cr2
import uuid #cr2 id запуска

from tools import call_tool, TOOL_SCHEMAS
from config import CONFIG

logger = logging.getLogger("harness") # cr2 логгер модуля
logger.setLevel(logging.INFO)
if not logger.handlers: # cr2 чтобы не дублировать
    handler = logging.FileHandler("harness.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)


def log_event(**fields):
    """Записать структурированное событие в журнал."""
    logger.info(json.dumps(fields, ensure_ascii=False)) # cr2 событие -> JSON-строка


def execute_tool(call):
    """cr3 Вызвать инструмент через единую точку входа."""
    name = call["function"]["name"]
    raw_args = call["function"]["arguments"]
    return call_tool(name, raw_args)


def tool_message(call_id, result):
    """Связать строковый результат с исходным вызовом модели."""
    return {
        "role": "tool", #результат вычислила не модель assistant а execute_tool
        "tool_call_id": call_id,
        "content": json.dumps(result, ensure_ascii=False, allow_nan=False),
    }


def run(ask_model, question, max_steps=None):
    """ask_model отправляет messages и tools в API и возвращает ответ модели."""
    if max_steps is None: #cr5
        max_steps = CONFIG["max_steps"]

    run_id = uuid.uuid4().hex[:8] # cr2 уникальный id запуска
    log_event(run_id=run_id, step=0, stage="start", status="ok") # cr2 старт

    messages = [
        {
            "role": "system",
            "content": (
                "Ты учебный помощник. Для вычислений используй инструменты. "
                "Получив результаты, ответь по-русски. Если инструмент вернул "
                "ошибку, объясни её; не выдумывай результат вычисления."
            ),
        },
        {"role": "user", "content": question},
    ]
    cur_step = 0  #cr1
    while True:
        if cur_step >= max_steps:  #cr1
            return {"status": "max_steps", "answer": None}  #cr1
        cur_step += 1 #cr1
        log_event(run_id=run_id, step=cur_step, stage="request_sent", status="ok") # cr2 отправляем запрос
        started = time.perf_counter() #cr2
        try:
            response = ask_model(messages=messages, tools=TOOL_SCHEMAS) #было-messages=question, messages-вся история диалога
        except Exception as error:
            if type(error).__name__ == "APITimeoutError":
                return {"status": "model_timeout", "answer": None}
            raise
        duration_ms = round((time.perf_counter() - started) * 1000, 1) # cr2 длительность
        message = response["message"]
        reason = response["finish_reason"]
        log_event(run_id=run_id, step=cur_step, stage="response_received",
                  status="ok", duration_ms=duration_ms) #cr2 ответ получ
        if reason not in ("stop", "tool_calls"):
            raise RuntimeError(f"Ответ модели не завершён: {reason}")
        messages.append(message)
        log_event(run_id=run_id, step=cur_step, stage="history_updated",
                  status="ok", role="assistant") #cr2 история + ответ модели
        calls = message.get("tool_calls") or []

        if not calls:
            if reason != "stop" or not isinstance(message.get("content"), str):
                raise RuntimeError("Модель не вернула ни вызовов, ни финального текста")
            return {"status": "ok", "answer": message["content"]} #if calls: убрала тк тогда просто идем в цикл
            #для cr1 изменила возврат- было - message["content"]


        for call in calls:
            call_id = call["id"]  # cr2: id вызова, нужен для связи tool-результата с запросом модели
            tool_name = call["function"]["name"]  # cr2: имя инструмента для лога
            log_event(run_id=run_id, step=cur_step, stage="tool_started",
                  status="ok", call_id=call_id, tool_name=tool_name)  # cr2: инструмент начали выполнять

            result = execute_tool(call)  # выполняем инструмент

            if isinstance(result, dict) and "error" in result:  # cr2: ошибка — это словарь с ключом error
                log_event(run_id=run_id, step=cur_step, stage="tool_error",
                      status="error", call_id=call_id, error=result["error"])  # cr2: пишем ошибку в лог

            messages.append(tool_message(call["id"], result))   # cr2: результат в историю
            log_event(run_id=run_id, step=cur_step, stage="history_updated",
                  status="ok", role="tool", call_id=call_id) # cr2: лог обновления истории