import tempfile
import pytest
from pathlib import Path
from app.config import settings
from app.database import init_db

@pytest.fixture(autouse=True, scope="session")
def isolate_test_database():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        test_db = Path(tmpdir) / "test_obrigado.db"
        orig_db = settings.db_path
        settings.db_path = test_db
        init_db()
        yield test_db
        settings.db_path = orig_db
