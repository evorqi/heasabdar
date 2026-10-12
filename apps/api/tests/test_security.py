from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hesabdar.config import Settings, ensure_network_is_locked
from hesabdar.errors import UnsafeBind
from hesabdar.main import create_app


def test_public_bind_without_token_is_refused(tmp_path) -> None:
    settings = Settings(data_dir=tmp_path / "data", host="0.0.0.0", access_token=None)
    with pytest.raises(UnsafeBind):
        ensure_network_is_locked(settings)
    with pytest.raises(UnsafeBind):
        create_app(settings)


def test_token_gates_requests_and_is_not_echoed(tmp_path) -> None:
    token = "super-secret-token"
    settings = Settings(data_dir=tmp_path / "data", host="127.0.0.1", access_token=token)
    app = create_app(settings)
    with TestClient(app) as client:
        missing = client.get("/api/health")
        assert missing.status_code == 403
        assert token not in missing.text
        wrong = client.get("/api/health", headers={"Authorization": "Bearer nope"})
        assert wrong.status_code == 403
        ok = client.get("/api/health", headers={"Authorization": f"Bearer {token}"})
        assert ok.status_code == 200
        assert ok.json() == {"status": "ok"}


def test_loopback_without_token_answers_health(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
