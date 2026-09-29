"""Один запрос к агенту; workspace — папка, из которой вызвали команду."""

import argparse
import logging
from pathlib import Path
import sys

from . import harness
from .clients import DeepSeekModel
from .config import Config
from .diagnostics import describe_error


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog=Path(sys.argv[0]).name.removesuffix(".exe"), description=__doc__,
        epilog='Пример: %(prog)s "Что в файле README.md?"',
    )
    parser.add_argument("question", nargs="+", help="Запрос, с кавычками или без")
    args = parser.parse_args(argv)
    question = " ".join(args.question).strip()
    if not question:
        parser.error("передайте непустой запрос")

    model = None
    try:
        root = Path.cwd().resolve(strict=True)
        config = Config.from_env(workspace_root=root)
        config.bind_workspace(root)
        if config.log_events:
            logging.basicConfig(level=logging.INFO, format="%(message)s")
        model = DeepSeekModel(config=config)
        result = harness.run(model, question, config)
        if result.reason == "max_steps":
            raise RuntimeError(
                f"max_steps: достигнут лимит {config.max_steps} запросов к модели"
            )
        if result.reason == "model_timeout":
            raise RuntimeError("model_timeout: модель не ответила за отведённое время")
        print(f"Ответ: {result.answer}")
        return 0
    except Exception as error:
        print(f"Ошибка: {describe_error(error)}", file=sys.stderr)
        return 1
    finally:
        if model is not None:
            model.close()


if __name__ == "__main__":
    sys.exit(main())
