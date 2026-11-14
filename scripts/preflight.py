#!/usr/bin/env python3
"""Run the gate preflight from a source checkout.

    python scripts/preflight.py
    python scripts/preflight.py --deep          # also load the detector
    python scripts/preflight.py --env-file "C:/ProgramData/VisionAI/gate.env"
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.preflight import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
