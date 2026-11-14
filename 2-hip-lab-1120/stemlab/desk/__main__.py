"""入口，只转调。python -m stemlab.desk ... 进界面的命令行。"""

from stemlab.desk.ui import cli  # noqa: F401

if __name__ == "__main__":
    raise SystemExit(cli.main())
