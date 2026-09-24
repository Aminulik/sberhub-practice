"""cr5 единая конфигурация harness."""
from pathlib import Path

CONFIG = {
    "max_steps": 8,
    "watchdog": 8,
    "model_timeout": 20.0,
    "tool_timeout": 5,
    "allowed_tools": ["add", "divide", "multiply", "subtraction", "read_file"],
    "workspace": Path("./workspace"),
}