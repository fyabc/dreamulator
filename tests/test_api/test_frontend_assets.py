from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dreamulator import api


@pytest.mark.parametrize(
    ("filename", "content_type"),
    [("pyodide.mjs", "application/javascript"), ("pyodide.asm.wasm", "application/wasm")],
)
def test_serves_browser_runtime_assets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, filename: str, content_type: str
) -> None:
    monkeypatch.setattr(api, "_frontend_dist", tmp_path)
    runtime_path = Path("playground-runtime") / "v314" / filename
    asset = tmp_path / runtime_path
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"runtime asset")

    response = TestClient(api.app).get(f"/{runtime_path.as_posix()}")

    assert response.status_code == 200
    assert response.headers["content-type"] == content_type
    assert response.content == b"runtime asset"
