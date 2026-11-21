"""Say what this environment holds, as one JSON line. Run on the worker with the environment's own python:

    <root>/venv/bin/python <root>/lock/report_env.py <root>/lock

It gives the interpreter, the hash of the lock the environment was installed from, every installed package with its
version, and whether each package the project names directly can really be imported (a package can be installed
and still fail to load, for example when the machine lacks a system library it needs). It changes nothing.
"""
import importlib
import importlib.metadata
import json
import pathlib
import platform
import re
import sys
import tomllib


def plain(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


lock_dir = pathlib.Path(sys.argv[1])
project = tomllib.loads((lock_dir / "pyproject.toml").read_text(encoding="utf-8"))
direct = [plain(re.match(r"[A-Za-z0-9._-]+", line).group(0)) for line in project["project"]["dependencies"]]
modules: dict = {}
for module, owners in importlib.metadata.packages_distributions().items():
    for owner in owners:
        modules.setdefault(plain(owner), set()).add(module)

installed_from = lock_dir / "installed-from.sha256"
found = {
    "host": platform.node(),
    "python": platform.python_version(),
    "executable": sys.executable,
    "lock": installed_from.read_text(encoding="utf-8").strip() if installed_from.is_file() else None,
    "packages": {plain(dist.metadata["Name"]): dist.version for dist in importlib.metadata.distributions()},
    "imports": {},
}
for name in direct:
    for module in sorted(modules.get(name, ())):
        if module.startswith("_"):
            continue
        try:
            importlib.import_module(module)
            found["imports"][module] = "ok"
        except Exception as error:  # noqa: BLE001  whatever stops the import is what we want to report
            found["imports"][module] = f"{type(error).__name__}: {error}"[:300]
print(json.dumps(found, sort_keys=True))
