import os
import sys
import tempfile
from pathlib import Path

# Settings are read at import time, so point storage at a throwaway folder before the app loads.
_tmp = tempfile.mkdtemp(prefix="substudio-test-")
os.environ["DATA_DIR"] = _tmp
os.environ["TRANSLATOR_PROVIDER"] = "mock"
os.environ["WEB_DIST"] = str(Path(_tmp) / "no-web")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
