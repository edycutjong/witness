import os
from pathlib import Path

import pytest

os.environ.setdefault("DO_NOT_TRACK", "1")

import relate  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def tiny_rl(tmp_path):
    """A 5-node graph where A reaches D through two hubs (redundant support) plus an unrelated type."""
    path = tmp_path / "tiny.rl"
    db = relate.Database(str(path))
    db.execute(
        "CREATE (a:P {name: 'A'}), (b:P {name: 'B'}), (c:P {name: 'C'}), (d:P {name: 'D'}), (e:Q {name: 'E'}),"
        " (a)-[:R]->(b), (a)-[:R]->(c), (b)-[:R]->(d), (c)-[:R]->(d), (a)-[:R]->(e), (e)-[:X]->(d)"
    )
    db.close()
    return path
