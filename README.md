# CareerAI — Career Risk & Prediction System

AI-powered career risk scoring, job trend forecasting, and upskilling roadmaps.

## Phase Status

| Phase | Feature | Status |
|-------|---------|--------|
| 1 | Core system (NLP, Risk Model, REST API, SQLite) | ✅ Done |
| 2 | JWT Auth, User Profiles, Saved Analyses | ✅ Done |
| 3 | XGBoost Model, Prophet Forecasting, APScheduler, Admin | ✅ Done |
| 4 | Rate Limiting, Real Email, Sentry, Docker, CI/CD | ✅ Done |

---

## Quick Start (Local)

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Copy and fill in your API keys
cp .env .env.local
# Edit .env — see API Keys section below

# 3. Run
python app.py
# → http://127.0.0.1:8000
```

---

## Files You Need to Edit

### `.env` — API Keys (required)

| Variable | Where to get it | Free tier |
|----------|----------------|-----------|
| `SECRET_KEY` | Run: `python -c "import secrets; print(secrets.token_hex(32))"` | N/A |
| `ADZUNA_APP_ID` + `ADZUNA_APP_KEY` | [developer.adzuna.com](https://developer.adzuna.com/) | 100 req/day |
| `BLS_API_KEY` | [bls.gov/developers](https://www.bls.gov/developers/) | 500 req/day |
| `ONET_USERNAME` + `ONET_PASSWORD` | [services.onetcenter.org](https://services.onetcenter.org/) | Unlimited |
| `SMTP_USER` + `SMTP_PASSWORD` | Gmail App Password at [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) | Free |
| `SENTRY_DSN` | [sentry.io](https://sentry.io) (optional) | 5k errors/month |

**Generate SECRET_KEY:**
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

**Gmail App Password (for real password reset emails):**
1. Go to myaccount.google.com → Security → 2-Step Verification → App passwords
2. Create app password for "Mail"
3. Paste the 16-character code into `SMTP_PASSWORD=`

---

## Docker Deployment

```bash
# 1. Fill in .env (especially SECRET_KEY, DB_PASSWORD)
# 2. Start all services
docker compose up -d

# 3. Check logs
docker compose logs -f api

# 4. Visit http://localhost (nginx) or http://localhost:8000 (api direct)
```

Services started:
- **api** — FastAPI on port 8000
- **db** — PostgreSQL 16 on port 5432
- **redis** — Redis 7 on port 6379
- **nginx** — Reverse proxy on port 80

---

## Deploy to Railway (free tier)

1. Push code to GitHub
2. Go to [railway.app](https://railway.app) → New Project → Deploy from GitHub
3. Add environment variables from `.env` in Railway dashboard
4. Railway auto-detects the `Dockerfile` and deploys

---

## CI/CD (GitHub Actions)

The pipeline at `.github/workflows/deploy.yml` runs on every push to `main`:

1. **Test** — runs `pytest tests/`
2. **Build** — builds Docker image
3. **Push** — pushes to Docker Hub
4. **Deploy** — deploys to Railway

**Required GitHub Secrets:**

| Secret | Value |
|--------|-------|
| `DOCKERHUB_USERNAME` | Your Docker Hub username |
| `DOCKERHUB_TOKEN` | Docker Hub access token |
| `RAILWAY_TOKEN` | Railway API token (`railway login` then copy from dashboard) |

---

## API Overview

### Auth
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/auth/register` | Register (rate limited: 10/min) |
| POST | `/api/v1/auth/login` | Login (rate limited: 10/min) |
| POST | `/api/v1/auth/refresh` | Refresh access token |
| POST | `/api/v1/auth/logout` | Revoke refresh token |
| GET  | `/api/v1/auth/me` | Get current user |
| POST | `/api/v1/auth/password-reset/request` | Send reset email |
| POST | `/api/v1/auth/password-reset/confirm` | Set new password |

### Career Intelligence (🔒 JWT required)
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/resume/parse` | Parse PDF/DOCX resume |
| POST | `/api/v1/risk/predict` | XGBoost risk score + SHAP |
| GET  | `/api/v1/trends/{role}` | Prophet forecast + history |
| POST | `/api/v1/skills/gap-analysis` | Skill gap vs target role |
| POST | `/api/v1/recommend/roadmap` | 18-month upskilling plan |

### Admin (🔒 admin role required)
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/admin/make-first-admin` | Bootstrap first admin |
| GET  | `/api/v1/admin/stats` | Users, analyses, model info |
| POST | `/api/v1/admin/retrain` | Trigger XGBoost retraining |
| GET  | `/api/v1/admin/users` | List all users |
| PATCH | `/api/v1/admin/users/{id}/deactivate` | Deactivate user |

---

## Become Admin (first time)

After registering your first account:
```bash
curl -X POST http://localhost:8000/api/v1/admin/make-first-admin \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```
This only works once — if an admin already exists, it returns 409.

---

## Running Tests

```bash
pytest tests/ -v

# Skip live API tests (no keys needed):
pytest tests/ -v --ignore=tests/test_live_apis.py
```
