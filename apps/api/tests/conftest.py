from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hesabdar.config import Settings
from hesabdar.main import create_app


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(data_dir=tmp_path / "data", host="127.0.0.1")


@pytest.fixture
def client(settings: Settings) -> TestClient:
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client
