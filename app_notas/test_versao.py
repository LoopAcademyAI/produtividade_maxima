import os
from unittest.mock import patch

from fastapi.testclient import TestClient

import app


def main():
    with (
        TestClient(app.app) as client,
        patch.dict(os.environ, {"APP_COMMIT_SHA": "0123456789abcdef"}),
    ):
        response = client.get("/api/versao")

    assert response.status_code == 200
    assert response.json() == {"commit": "0123456"}


if __name__ == "__main__":
    main()
