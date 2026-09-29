"""Один запрос пользователя к harness с настоящим DeepSeek Flash."""

import argparse
from pathlib import Path
import sys

from . import harness
from .clients import DeepSeekModel
from .config import Config
from .diagnostics import describe_error


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, usage='%(prog)s "запрос пользователя"', add_help=False,
    )
    parser.add_argument("question", nargs="?", help="Запрос пользователя в кавычках")
    parser.add_argument("-h", "--help", action="help", help="Показать справку")
    args = parser.parse_args(argv)
    if not args.question or not args.question.strip():
        print('Ошибка: передайте непустой запрос, например: python run.py "Сложи 18 и 24"', file=sys.stderr)
        return 2

    model = None
    try:
        root = Path.cwd().resolve(strict=True)
        config = Config.from_env(workspace_root=root)
        config.bind_workspace(root)
        model = DeepSeekModel(config=config)
        result = harness.run(model, args.question, config)
        if result["status"] == "ok":
            print(f"Ответ: {result['answer']}")
            return 0
        if result["status"] == "max_steps":
            print("Ошибка: достигнут лимит шагов.", file=sys.stderr)
            return 1
        if result["status"] == "model_timeout":
            print("Ошибка: модель не ответила за отведённое время.", file=sys.stderr)
            return 1
        raise RuntimeError(f"Неизвестный статус: {result['status']}")
    except Exception as error:
        print(f"Ошибка: {describe_error(error)}", file=sys.stderr)
        return 1
    finally:
        if model is not None:
            model.close()


if __name__ == "__main__":
    sys.exit(main())
