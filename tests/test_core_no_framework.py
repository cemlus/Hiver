"""src/core is framework-free: importing it must not pull in langgraph or src.integrations.

src/core/__init__.py has always claimed this test enforces the rule; it did not exist until now.
The subprocess pattern is the one tests/test_ports.py uses for the optional-dependency check.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN = ("langgraph", "langchain", "src.integrations")


def test_importing_core_loads_no_framework():
    code = (
        "import sys;"
        "import src.core.classify, src.core.route, src.core.escalate, src.core.cues,"
        " src.core.retrieve, src.core.draft, src.core.validate, src.core.respond;"
        f"bad=[m for m in {FORBIDDEN!r} if m in sys.modules];"
        "print(','.join(bad))"
    )
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "", f"src/core imported: {result.stdout.strip()}"


def test_importing_core_loads_no_sentence_transformers():
    """Retrieval imports the embedding model lazily, so core stays cheap to import."""
    code = ("import sys; import src.core.retrieve;"
            "print('sentence_transformers' in sys.modules or 'torch' in sys.modules)")
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False"
