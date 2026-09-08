import shutil
import subprocess
from pathlib import Path

import pytest

TF_DIR = Path(__file__).resolve().parent.parent / "deploy" / "terraform"
terraform = shutil.which("terraform")
pytestmark = pytest.mark.skipif(terraform is None, reason="terraform not installed")


def _tf(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([terraform, *args], cwd=TF_DIR, capture_output=True, text=True, timeout=300)


def test_terraform_fmt_and_validate():
    assert _tf("fmt", "-check", "-recursive").returncode == 0, "run terraform fmt"
    init = _tf("init", "-backend=false", "-input=false", "-no-color")
    assert init.returncode == 0, init.stderr
    validate = _tf("validate", "-no-color")
    assert validate.returncode == 0, validate.stdout + validate.stderr
    assert "Success" in validate.stdout
