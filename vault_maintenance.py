#!/usr/bin/env python3
"""Repository entry point; the copyable skill owns the standalone implementation."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent / "skills" / "vault-maintenance" / "scripts"))
from maintain_vault import (  # noqa: E402,F401
    apply_plan, build_plan, lint_text, main, read_changes,
    recover_journal, transaction_operations,
)

if __name__ == "__main__":
    raise SystemExit(main())
