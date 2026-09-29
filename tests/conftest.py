import os
import sys
from pathlib import Path

# Add backend directory to sys.path so 'app' modules can be imported directly
BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# ---------------------------------------------------------------------------
# SECURITY TEST SETUP: the API requires an X-API-Token on every /api/* call
# (see app/main.py :: api_token_guard). For the test suite we pin a fixed
# token via the environment BEFORE the app is imported, and transparently
# attach it to every TestClient request so existing tests keep passing
# without editing each call site. This lives only in tests — production
# builds never see it.
# ---------------------------------------------------------------------------
os.environ.setdefault("API_TOKEN", "test-token-local-only-do-not-use-in-prod")

from fastapi.testclient import TestClient  # noqa: E402

_TEST_API_TOKEN = os.environ["API_TOKEN"]

_original_request = TestClient.request


def _request_with_api_token(self, method, url, *args, **kwargs):
    headers = dict(kwargs.pop("headers", None) or {})
    headers.setdefault("X-API-Token", _TEST_API_TOKEN)
    kwargs["headers"] = headers
    return _original_request(self, method, url, *args, **kwargs)


TestClient.request = _request_with_api_token
