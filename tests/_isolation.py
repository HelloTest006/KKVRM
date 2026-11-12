"""Point every per-user location at a throwaway directory before any test runs.

Without this, tests read the developer's real ``%APPDATA%/kkvrm/config.json``
(stored Blender path, default profile, export root, metadata) and can pass or
fail depending on whoever runs them. Each test module imports this first.
"""

import atexit
import os
import shutil
import tempfile
from pathlib import Path

ROOT = Path(tempfile.mkdtemp(prefix="kkvrm-tests-"))
atexit.register(shutil.rmtree, ROOT, ignore_errors=True)

for variable in ("APPDATA", "LOCALAPPDATA", "HOME", "USERPROFILE"):
    (ROOT / variable).mkdir(exist_ok=True)
    os.environ[variable] = str(ROOT / variable)
for variable in ("KKVRM_BLENDER", "BLENDER"):
    os.environ.pop(variable, None)
