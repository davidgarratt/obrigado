import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.config import settings
from app.services.openrouter_service import openrouter_service
from app.services.gemini_service import gemini_service

client = TestClient(app)

def test_openrouter_status_and_config():
    # 1. Initial status check
    res = client.get("/api/settings/status")
    assert res.status_code == 200
    data = res.json()
    assert "openrouter_configured" in data
    assert "openrouter_model" in data

    # 2. Configure OpenRouter credentials via API
    test_key = "sk-or-v1-test-token-12345"
    test_model = "anthropic/claude-3.5-sonnet"
    post_res = client.post("/api/settings/openrouter", json={
        "openrouter_api_key": test_key,
        "openrouter_model": test_model,
        "llm_provider": "auto"
    })
    assert post_res.status_code == 200
    post_data = post_res.json()
    assert post_data["success"] is True
    assert post_data["openrouter_configured"] is True
    assert post_data["openrouter_model"] == test_model

    # 3. Verify service reflects update
    assert openrouter_service.is_configured() is True
    assert openrouter_service.api_key == test_key
    assert openrouter_service.model == test_model

    # 4. Verify status endpoint reflects updated config
    res_after = client.get("/api/settings/status")
    assert res_after.status_code == 200
    data_after = res_after.json()
    assert data_after["openrouter_configured"] is True
    assert data_after["openrouter_model"] == test_model

    # 5. Clean up test token so other tests use Gemini
    openrouter_service.update_credentials("", settings.openrouter_model)
    settings.openrouter_api_key = ""
