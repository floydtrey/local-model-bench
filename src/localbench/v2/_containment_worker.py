from __future__ import annotations

import json
import subprocess
import sys
from typing import Any


def _request() -> dict[str, Any]:
    value = json.load(sys.stdin)
    if not isinstance(value, dict):
        raise ValueError("containment worker request must be an object")
    command = value.get("command")
    if not isinstance(command, list) or not command or any(
        not isinstance(item, str) or not item for item in command
    ):
        raise ValueError("containment worker command must be a non-empty string array")
    cwd = value.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        raise ValueError("containment worker cwd must be a non-empty string")
    env = value.get("env")
    if not isinstance(env, dict) or any(
        not isinstance(key, str) or not isinstance(item, str) for key, item in env.items()
    ):
        raise ValueError("containment worker env must be a string map")
    return {"command": command, "cwd": cwd, "env": env}


def main() -> int:
    request = _request()
    process = subprocess.Popen(
        request["command"],
        cwd=request["cwd"],
        env=request["env"],
    )
    return_code = process.wait()
    if return_code < 0:
        return 128 + min(abs(return_code), 127)
    return min(return_code, 255)


if __name__ == "__main__":
    raise SystemExit(main())
