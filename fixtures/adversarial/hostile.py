"""Scanned code is untrusted data. This module must never be imported."""
from pathlib import Path
Path("SCANNER_EXECUTION_CANARY").write_text("target code was executed")
raise RuntimeError("This fixture must never execute")
