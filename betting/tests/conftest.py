import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vb.db import session   # noqa: E402


@pytest.fixture
def conn(tmp_path):
    with session(tmp_path / "test.db") as connection:
        yield connection
