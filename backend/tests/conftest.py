import os
import sys
import tempfile

import pytest

# Ensure the backend/ directory (containing the `app` package) is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TMP_DIR = tempfile.mkdtemp(prefix="doc_intel_test_")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TMP_DIR}/test.db")
os.environ.setdefault("UPLOAD_DIR", os.path.join(_TMP_DIR, "uploads"))
os.environ.setdefault("ANTHROPIC_API_KEY", "")  # force offline fallback in tests
os.environ.setdefault("ALLOW_OFFLINE_EXTRACTION_FALLBACK", "true")
os.environ.setdefault("ENVIRONMENT", "test")

from app.core.config import get_settings  # noqa: E402

get_settings.cache_clear()


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
