"""История пар вопрос-ответ. У каждой папки свой файл вне workspace."""

import hashlib
import json
import os
from pathlib import Path
import tempfile


def memory_root():
    return Path.home() / ".chtagent" / "memory"


def _agent_env():
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False, encoding="utf-8-sig")


def history_turns():
    _agent_env()
    raw = os.environ.get("HISTORY_TURNS", "10")
    if not isinstance(raw, str) or not raw.strip().isdecimal():
        raise ValueError("HISTORY_TURNS должен быть целым числом >= 0")
    return int(raw.strip())


def memory_path(workspace_root):
    root = Path(workspace_root).resolve()
    key = hashlib.sha256(os.path.normcase(str(root)).encode("utf-8")).hexdigest()
    return memory_root() / f"{key}.json"


def _read_turns(path):
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("файл памяти повреждён") from error
    turns = data.get("turns") if isinstance(data, dict) else None
    if not isinstance(turns, list):
        raise ValueError("файл памяти повреждён")
    clean = []
    for turn in turns:
        if not isinstance(turn, dict):
            raise ValueError("файл памяти повреждён")
        user = turn.get("user")
        assistant = turn.get("assistant")
        if not isinstance(user, str) or not isinstance(assistant, str):
            raise ValueError("файл памяти повреждён")
        clean.append({"user": user, "assistant": assistant})
    return clean


def _write_turns(path, turns):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".mem-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump({"turns": turns}, stream, ensure_ascii=False)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def load_messages(workspace_root):
    limit = history_turns()
    if limit == 0:
        return []
    turns = _read_turns(memory_path(workspace_root))[-limit:]
    messages = []
    for turn in turns:
        messages.append({"role": "user", "content": turn["user"]})
        messages.append({"role": "assistant", "content": turn["assistant"]})
    return messages


def remember(workspace_root, question, answer):
    limit = history_turns()
    path = memory_path(workspace_root)
    if limit == 0:
        if path.exists():
            _write_turns(path, [])
        return
    turns = _read_turns(path)
    turns.append({"user": question, "assistant": answer})
    _write_turns(path, turns[-limit:])
