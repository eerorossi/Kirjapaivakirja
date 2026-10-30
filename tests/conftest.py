import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from store import Store  # noqa: E402


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "test.db"))


@pytest.fixture
def client(store):
    # FastAPI tuodaan vasta tässä, jotta Store-testit toimivat ilman sitä.
    from fastapi.testclient import TestClient

    from main import create_app

    with TestClient(create_app(store)) as c:
        yield c
