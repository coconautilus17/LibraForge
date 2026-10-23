"""Load the standalone scripts under scripts/ as modules, for tests.

The scripts are not importable packages (hyphens in their names), so tests load
them by path. The Audible client library is optional in the test environment;
without it a stub is installed so the Metadata Fixer script can still be imported.
"""
import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).parents[2]

try:
    import audible  # noqa: F401
except ModuleNotFoundError:
    _stub = types.ModuleType("audible")
    _stub.Client = type("Client", (), {})
    _stub.Authenticator = type("Authenticator", (), {})
    sys.modules["audible"] = _stub


def load_module(module_name: str, relative_path: str):
    """Load any source file (a script, or a module by path) relative to the repo root."""
    spec = importlib.util.spec_from_file_location(module_name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_script(module_name: str, filename: str):
    return load_module(module_name, f"scripts/{filename}")
