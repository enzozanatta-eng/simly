import shutil

import pytest

needs_solver = pytest.mark.skipif(shutil.which("ccx") is None, reason="CalculiX not installed")
