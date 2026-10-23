"""Web test helpers: an app on the fake bridge and an authenticated client."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from iterthink.services.bridge_fake import FakeBridge
from iterthink.web.app import TOKEN_HEADER, create_app

TOKEN = "test-token"


@pytest.fixture
def bridge() -> FakeBridge:
    return FakeBridge()


@pytest.fixture
def client(bridge: FakeBridge) -> TestClient:
    app = create_app(bridge=bridge, token=TOKEN, actor="user:simon")
    return TestClient(app, headers={TOKEN_HEADER: TOKEN, "accept": "text/html"})


@pytest.fixture
def project_id(bridge: FakeBridge, project_dir: Path) -> str:
    return bridge.make_project(project_dir).id
