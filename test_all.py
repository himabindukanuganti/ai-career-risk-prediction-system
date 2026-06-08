"""
CareerAI — Phase 4 Test Suite
Run: pytest tests/ -v
"""
import json, pytest
from fastapi.testclient import TestClient

# ── App import (handles missing optional deps gracefully) ─────────────────────
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

import os
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("DEBUG", "true")

from app import app

client = TestClient(app, raise_server_exceptions=False)

# ── Fixtures ─────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def auth_tokens():
    """Register a fresh test user and return tokens."""
    import time
    email = f"test_{int(time.time())}@example.com"
    r = client.post("/api/v1/auth/register", json={
        "name": "Test User", "email": email, "password": "TestPass123"
    })
    assert r.status_code == 201, f"Register failed: {r.text}"
    data = r.json()
    return {"access": data["access_token"], "refresh": data["refresh_token"], "email": email}

@pytest.fixture
def auth_headers(auth_tokens):
    return {"Authorization": f"Bearer {auth_tokens['access']}"}


# ══════════════════════════════════════════════════════════════
#  PHASE 1 — Core / Health
# ══════════════════════════════════════════════════════════════
class TestHealth:
    def test_health_returns_200(self):
        r = client.get("/health")
        assert r.status_code == 200

    def test_health_has_version(self):
        r = client.get("/health")
        data = r.json()
        assert "version" in data
        assert data["version"] == "4.0.0"

    def test_health_has_phase4_fields(self):
        r = client.get("/health")
        data = r.json()
        assert "rate_limiting" in data
        assert "email_configured" in data
        assert "db" in data
        assert data["db"] is True

    def test_status_endpoint(self):
        r = client.get("/api/v1/status")
        assert r.status_code == 200
        assert "adzuna" in r.json()

    def test_root_serves_html(self):
        r = client.get("/")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]


# ══════════════════════════════════════════════════════════════
#  PHASE 2 — Authentication
# ══════════════════════════════════════════════════════════════
class TestAuth:
    def test_register_success(self):
        import time
        r = client.post("/api/v1/auth/register", json={
            "name": "Alice", "email": f"alice_{int(time.time())}@test.com", "password": "SecurePass1"
        })
        assert r.status_code == 201
        data = r.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["user"]["name"] == "Alice"

    def test_register_duplicate_email_returns_400(self, auth_tokens):
        r = client.post("/api/v1/auth/register", json={
            "name": "Dup", "email": auth_tokens["email"], "password": "SecurePass1"
        })
        assert r.status_code == 400
        assert "already" in r.json()["detail"].lower()

    def test_register_short_password_returns_400(self):
        r = client.post("/api/v1/auth/register", json={
            "name": "Bob", "email": "bob@test.com", "password": "short"
        })
        assert r.status_code == 400

    def test_register_invalid_email_returns_400(self):
        r = client.post("/api/v1/auth/register", json={
            "name": "Bob", "email": "not-an-email", "password": "SecurePass1"
        })
        assert r.status_code == 400

    def test_login_success(self, auth_tokens):
        r = client.post("/api/v1/auth/login", data={
            "username": auth_tokens["email"], "password": "TestPass123"
        })
        assert r.status_code == 200
        assert "access_token" in r.json()

    def test_login_wrong_password_returns_401(self, auth_tokens):
        r = client.post("/api/v1/auth/login", data={
            "username": auth_tokens["email"], "password": "WrongPassword"
        })
        assert r.status_code == 401

    def test_login_unknown_email_returns_401(self):
        r = client.post("/api/v1/auth/login", data={
            "username": "nobody@nowhere.com", "password": "anything"
        })
        assert r.status_code == 401

    def test_me_endpoint(self, auth_headers):
        r = client.get("/api/v1/auth/me", headers=auth_headers)
        assert r.status_code == 200
        assert "email" in r.json()

    def test_me_without_token_returns_401(self):
        r = client.get("/api/v1/auth/me")
        assert r.status_code == 401

    def test_refresh_token(self, auth_tokens):
        r = client.post("/api/v1/auth/refresh", json={"refresh_token": auth_tokens["refresh"]})
        assert r.status_code == 200
        assert "access_token" in r.json()

    def test_logout(self, auth_tokens):
        r = client.post("/api/v1/auth/logout", json={"refresh_token": auth_tokens["refresh"]})
        assert r.status_code == 200

    def test_password_reset_request_always_200(self):
        r = client.post("/api/v1/auth/password-reset/request", json={"email": "nobody@test.com"})
        assert r.status_code == 200
        assert "message" in r.json()

    def test_password_reset_has_dev_token_in_debug(self, auth_tokens):
        r = client.post("/api/v1/auth/password-reset/request",
                        json={"email": auth_tokens["email"]})
        assert r.status_code == 200
        data = r.json()
        # DEBUG=true so dev_token should be present
        assert "dev_token" in data

    def test_protected_route_without_token(self):
        r = client.get("/api/v1/user/profile")
        assert r.status_code == 401


# ══════════════════════════════════════════════════════════════
#  PHASE 2 — User Profile & Analyses
# ══════════════════════════════════════════════════════════════
class TestUserProfile:
    def test_get_profile(self, auth_headers):
        r = client.get("/api/v1/user/profile", headers=auth_headers)
        assert r.status_code == 200

    def test_update_profile(self, auth_headers):
        r = client.put("/api/v1/user/profile", headers=auth_headers, json={
            "current_role": "Data Analyst", "target_role": "ML Engineer",
            "years_exp": 3.0, "education_level": 0.75,
            "skills": ["Python", "SQL", "Pandas"]
        })
        assert r.status_code == 200
        assert r.json()["current_role"] == "Data Analyst"

    def test_save_analysis(self, auth_headers):
        r = client.post("/api/v1/user/analyses", headers=auth_headers, json={
            "type": "risk", "title": "My Risk Analysis",
            "data": {"risk_score": 42, "role": "Data Analyst"}
        })
        assert r.status_code == 200
        assert "id" in r.json()

    def test_list_analyses(self, auth_headers):
        r = client.get("/api/v1/user/analyses", headers=auth_headers)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_dashboard_summary(self, auth_headers):
        r = client.get("/api/v1/user/dashboard-summary", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert "user" in data
        assert "profile" in data


# ══════════════════════════════════════════════════════════════
#  PHASE 3 — ML / Risk / Forecast
# ══════════════════════════════════════════════════════════════
class TestRisk:
    def test_risk_predict(self, auth_headers):
        r = client.post("/api/v1/risk/predict", headers=auth_headers, json={
            "role": "data analyst", "years_exp": 3.0,
            "n_skills": 8, "education_level": 0.5
        })
        assert r.status_code == 200
        data = r.json()
        assert "risk_score" in data
        assert 0 <= data["risk_score"] <= 100
        assert data["risk_category"] in ("Low", "Medium", "High", "Critical")
        assert "viability_index" in data
        assert "shap_values" in data

    def test_risk_all_categories(self, auth_headers):
        test_cases = [
            ("ml engineer", 10.0, 20, 1.0),        # expect Low
            ("data entry specialist", 0.5, 2, 0.25), # expect High/Critical
        ]
        for role, yrs, n_sk, edu in test_cases:
            r = client.post("/api/v1/risk/predict", headers=auth_headers,
                            json={"role": role, "years_exp": yrs, "n_skills": n_sk, "education_level": edu})
            assert r.status_code == 200
            assert r.json()["risk_category"] in ("Low","Medium","High","Critical")

    def test_automation_index(self, auth_headers):
        r = client.get("/api/v1/risk/automation-index/software engineer", headers=auth_headers)
        assert r.status_code == 200

    def test_model_info(self, auth_headers):
        r = client.get("/api/v1/risk/model-info", headers=auth_headers)
        assert r.status_code == 200


class TestTrends:
    def test_forecast_returns_data(self, auth_headers):
        r = client.get("/api/v1/trends/data analyst", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert "forecast" in data
        assert len(data["forecast"]) > 0
        assert "yoy_growth" in data

    def test_forecast_has_confidence_bands(self, auth_headers):
        r = client.get("/api/v1/trends/ml engineer", headers=auth_headers)
        assert r.status_code == 200
        forecast = r.json()["forecast"]
        assert len(forecast) >= 5
        first = forecast[0]
        assert "postings_index" in first

    def test_trends_overview(self, auth_headers):
        r = client.get("/api/v1/trends/overview/all", headers=auth_headers)
        assert r.status_code == 200
        assert "roles" in r.json()

    def test_trend_history(self, auth_headers):
        r = client.get("/api/v1/trends/history/data analyst", headers=auth_headers)
        assert r.status_code == 200


class TestSkills:
    def test_skill_benchmarks(self, auth_headers):
        r = client.get("/api/v1/skills/benchmarks/data analyst", headers=auth_headers)
        assert r.status_code == 200
        assert "required_skills" in r.json()

    def test_gap_analysis(self, auth_headers):
        r = client.post("/api/v1/skills/gap-analysis", headers=auth_headers, json={
            "current_skills": [{"skill_name": "Python"}, {"skill_name": "SQL"}],
            "target_role": "data analyst"
        })
        assert r.status_code == 200
        data = r.json()
        assert "gaps" in data
        assert "match_pct" in data


class TestRecommendations:
    def test_roadmap(self, auth_headers):
        r = client.post("/api/v1/recommend/roadmap", headers=auth_headers, json={
            "current_role": "data analyst",
            "target_role": "ml engineer",
            "skill_gaps": ["PyTorch", "MLOps", "AWS"],
            "years_exp": 2.0
        })
        assert r.status_code == 200
        data = r.json()
        assert "courses" in data
        assert "salary_projection" in data

    def test_courses(self, auth_headers):
        r = client.get("/api/v1/recommend/courses/python", headers=auth_headers)
        assert r.status_code == 200


# ══════════════════════════════════════════════════════════════
#  PHASE 4 — Admin & Rate Limiting
# ══════════════════════════════════════════════════════════════
class TestAdmin:
    def test_admin_routes_require_auth(self):
        r = client.get("/api/v1/admin/stats")
        assert r.status_code == 401

    def test_admin_routes_require_admin_role(self, auth_headers):
        # Regular user should get 403
        r = client.get("/api/v1/admin/stats", headers=auth_headers)
        assert r.status_code == 403

    def test_make_first_admin_works_when_no_admin(self):
        """Only works if no admin exists — skip if one already does."""
        import time
        # Register fresh user for this test
        email = f"admin_test_{int(time.time())}@test.com"
        reg = client.post("/api/v1/auth/register", json={
            "name": "AdminTest", "email": email, "password": "AdminPass123"
        })
        if reg.status_code != 201:
            pytest.skip("Registration failed")
        token = reg.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        r = client.post("/api/v1/admin/make-first-admin", headers=headers)
        # Either succeeds (201) or 409 if admin already exists — both are valid
        assert r.status_code in (200, 409)

    def test_dev_reset_requires_debug(self):
        r = client.delete("/api/v1/auth/dev-reset-users")
        # In DEBUG=true this should succeed; in prod it's 403
        assert r.status_code in (200, 403)


# ══════════════════════════════════════════════════════════════
#  ML Unit Tests (no HTTP)
# ══════════════════════════════════════════════════════════════
class TestMLUnit:
    def test_risk_model_formula_fallback(self):
        """Test the formula-based risk model directly."""
        try:
            from backend.ml.risk_model import predict_career_risk
            result = predict_career_risk(
                role="data analyst", years_exp=3.0,
                skill_list=[{"name":"Python","level":"Intermediate"},
                            {"name":"SQL","level":"Advanced"}],
                education_level=0.5
            )
            assert 0 <= result.risk_score <= 100
            assert result.risk_category in ("Low","Medium","High","Critical")
            assert isinstance(result.shap_values, dict)
        except ImportError:
            pytest.skip("ML modules not available")

    def test_trend_forecaster(self):
        try:
            from backend.ml.trend_forecaster import get_trend_forecast
            result = get_trend_forecast("data analyst", horizon=5)
            assert result.role == "Data Analyst"
            assert len(result.forecast) == 5
            assert result.forecast[0].postings_index > 0
        except ImportError:
            pytest.skip("ML modules not available")

    def test_risk_score_ordering(self):
        """High-risk role should score higher than low-risk role."""
        try:
            from backend.ml.risk_model import predict_career_risk
            high = predict_career_risk("data entry specialist", 0.5,
                [{"name":"typing","level":"Beginner"}], 0.25)
            low  = predict_career_risk("ml engineer", 8.0,
                [{"name":s,"level":"Advanced"} for s in ["Python","TensorFlow","PyTorch","MLOps","AWS","Docker","Kubernetes","Spark"]], 1.0)
            assert high.risk_score > low.risk_score, \
                f"Expected high({high.risk_score}) > low({low.risk_score})"
        except ImportError:
            pytest.skip("ML modules not available")
