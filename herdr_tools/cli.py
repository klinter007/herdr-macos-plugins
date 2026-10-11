import importlib
import os
import sys

from .common import notify


def main():
    feature, command = sys.argv[1:3]
    if feature not in ("files", "metrics", "awake", "jev"):
        raise ValueError("Unknown feature")
    try:
        importlib.import_module(f"herdr_tools.{feature}").main(command)
    except (Exception, KeyboardInterrupt) as error:
        message = str(error) or "Cancelled."
        print(message, file=sys.stderr)
        if command != "watch":
            try:
                notify(message)
            except Exception:
                pass
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
