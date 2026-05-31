# DevMentor AI

**Production-grade AI-powered developer coaching platform.**

Practice technical interviews, receive semantic AI scoring, detect skill gaps, and follow a personalized learning roadmap — all running locally on CPU with no paid cloud infrastructure required beyond a free Groq API key.

---

## Architecture

```
Internet
    ↓
Nginx (port 80) — reverse proxy, rate limiting, SSL termination
    ↓
┌─────────────────┬──────────────────┐
│ Next.js         │ FastAPI          │
│ Frontend        │ Backend (8000)   │
│ (port 3000)     │                  │
└─────────────────┴──────────────────┘
                      ↓
          ┌───────────┼───────────┐
          │           │           │
       Postgres    Redis       ML Service
       (5432)      (6379)      (8001)
                               ↓
                   ┌───────────┼───────────┐
                   │           │           │
              Sentence    Groq LLM    TF-IDF +
           Transformers  (free tier)  Logistic Reg
```

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 14, TypeScript |
| API | FastAPI, Python 3.11, SQLAlchemy |
| Auth | JWT (access + refresh), bcrypt |
| Cache | Redis (cache-aside, sessions, rate limiting) |
| Database | PostgreSQL 16, Alembic migrations |
| ML — Evaluation | Sentence Transformers (all-MiniLM-L6-v2) |
| ML — Classification | TF-IDF + Logistic Regression |
| ML — Feedback | Groq Llama 3.3-70B (free tier) |
| Gateway | Nginx |
| CI/CD | GitHub Actions (4 workflows) |
| Containers | Docker + Docker Compose |

## Quick Start

### Prerequisites

- Docker + Docker Compose
- A free [Groq API key](https://console.groq.com) (takes 60 seconds)

### 1. Clone and configure

```bash
git clone https://github.com/your-username/devmentor-ai.git
cd devmentor-ai
cp .env.example .env
```

Open `.env` and set your Groq API key:

```
GROQ_API_KEY=gsk_your_key_here
```

Generate a secure secret key:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
# Paste output into .env as SECRET_KEY=...
```

### 2. Start everything

```bash
docker compose up --build
```

First run downloads the Sentence Transformer model (~90MB). Subsequent starts are instant.

### 3. Access

| Service | URL |
|---|---|
| App | http://localhost |
| API docs | http://localhost/docs |
| Health check | http://localhost/health |
| Prometheus metrics | http://localhost/metrics |

### 4. Create your account

Visit http://localhost/register — no email verification required.

---

## Makefile Commands

```bash
make help          # Show all commands
make setup         # First-time setup
make dev           # Start all services (hot reload)
make test          # Run all 171 tests
make test-backend  # Backend tests only
make test-ml       # ML service tests only
make lint          # Run ruff + eslint
make migrate       # Run database migrations
make migrate-new msg="add column"  # Create new migration
make health        # Check all service health
make logs          # Tail all service logs
make shell-backend # Shell into backend container
make shell-db      # psql into Postgres
make redis-cli     # Redis CLI
make clean         # Remove all containers and volumes
```

---

## Project Structure

```
devmentor-ai/
├── backend/                    # FastAPI application
│   ├── app/
│   │   ├── api/v1/endpoints/   # HTTP route handlers
│   │   │   ├── auth.py         # Register, login, refresh, logout
│   │   │   ├── interview.py    # Session lifecycle, Q&A, scoring
│   │   │   ├── code_review.py  # AI code review
│   │   │   └── roadmap.py      # Skill assessments, roadmap
│   │   ├── core/               # Cross-cutting concerns
│   │   │   ├── config.py       # Pydantic Settings (reads .env)
│   │   │   ├── security.py     # JWT + bcrypt
│   │   │   ├── dependencies.py # FastAPI DI (get_current_user)
│   │   │   ├── logging.py      # Structured JSON logging
│   │   │   ├── metrics.py      # Prometheus counters/histograms
│   │   │   └── middleware.py   # Observability + rate limiting
│   │   ├── db/
│   │   │   ├── session.py      # Async SQLAlchemy engine + pool
│   │   │   └── redis.py        # Redis connection pool
│   │   ├── models/             # SQLAlchemy ORM models
│   │   ├── schemas/            # Pydantic request/response schemas
│   │   └── services/           # Business logic layer
│   │       ├── auth_service.py
│   │       ├── interview_service.py  # Full session lifecycle
│   │       ├── cache_service.py      # Redis patterns
│   │       ├── ml_client.py          # HTTP client for ML service
│   │       ├── health_service.py     # Liveness + readiness checks
│   │       └── recommendation_service.py
│   ├── alembic/                # Database migrations
│   │   └── versions/
│   │       └── 0001_initial_schema.py
│   ├── tests/                  # 81 unit tests
│   ├── Dockerfile
│   ├── requirements.txt
│   └── pyproject.toml          # Ruff, mypy, pytest config
│
├── ml/                         # ML microservice (port 8001)
│   ├── evaluator/
│   │   └── evaluator.py        # Sentence Transformer scoring
│   ├── classifier/
│   │   ├── tfidf_classifier.py # TF-IDF + Logistic Regression
│   │   └── skill_classifier.py # Groq + TF-IDF orchestration
│   ├── llm/
│   │   ├── groq_client.py      # Groq API with retry + JSON mode
│   │   └── feedback_generator.py  # LLM coaching feedback
│   ├── recommender/
│   │   ├── catalogue.py        # 30 curated learning resources
│   │   └── engine.py           # Content-based + Groq personalization
│   ├── tests/                  # 90 unit tests
│   ├── main.py                 # FastAPI ML service
│   ├── Dockerfile
│   └── requirements.txt
│
├── frontend/                   # Next.js application
│   └── src/
│       ├── pages/
│       │   ├── index.tsx       # Landing page (SSG)
│       │   ├── login.tsx       # Auth pages
│       │   ├── register.tsx
│       │   ├── dashboard.tsx   # Skill radar + sessions (CSR)
│       │   ├── interview.tsx   # Interview room (CSR, real API)
│       │   └── roadmap.tsx     # Learning roadmap (CSR)
│       ├── hooks/
│       │   ├── useAuth.ts      # Auth state + silent refresh
│       │   └── useApi.ts       # Generic data fetching
│       ├── utils/
│       │   └── api.ts          # Typed API client
│       └── styles/
│           └── globals.css     # Design system (Terminal Precision)
│
├── nginx/
│   ├── nginx.conf              # Reverse proxy + rate limiting
│   └── Dockerfile
│
├── .github/
│   └── workflows/
│       ├── ci.yml              # Lint → Test → Security → Build
│       ├── cd.yml              # Deploy staging + production
│       ├── pr-checks.yml       # PR quality gates
│       └── dependency-update.yml  # Weekly CVE scanning
│
├── docker-compose.yml          # Orchestrates all 6 services
├── .env.example                # Environment template
├── Makefile                    # Developer commands
└── README.md
```

---

## API Reference

### Authentication

```
POST /api/v1/auth/register    Create account
POST /api/v1/auth/login       Login → access + refresh tokens
POST /api/v1/auth/refresh     Exchange refresh token for new access token
GET  /api/v1/auth/me          Current user profile
POST /api/v1/auth/logout      Revoke session
```

### Interview Sessions

```
POST /api/v1/interview/                          Start session
GET  /api/v1/interview/                          List sessions
GET  /api/v1/interview/{id}                      Session details
GET  /api/v1/interview/{id}/questions            Get questions
POST /api/v1/interview/questions/{id}/submit     Submit answer (ML scored)
POST /api/v1/interview/{id}/complete             Complete session
POST /api/v1/interview/{id}/abandon              Abandon session
GET  /api/v1/interview/{id}/results              Full results review
```

### Code Review

```
POST /api/v1/code-review/    Submit code for AI review
```

### Roadmap & Skills

```
GET   /api/v1/roadmap/skills           Skill proficiency scores
GET   /api/v1/roadmap/roadmap          Personalized learning roadmap
PATCH /api/v1/roadmap/roadmap/{id}     Mark resource complete
```

### Monitoring

```
GET /health          Liveness probe (no external checks)
GET /health/ready    Readiness probe (DB + Redis + ML)
GET /metrics         Prometheus metrics
```

---

## ML Pipeline

### Answer Evaluation (Module 1)

1. Candidate answer + ideal answer → Sentence Transformer encoder
2. 384-dimensional embeddings → cosine similarity (content score)
3. Rule-based confidence score (length, keyword coverage, structure)
4. Weighted combination: 70% content + 30% confidence
5. Groq LLM generates personalized coaching feedback

### Skill Classification (Module 2)

1. Question text → TF-IDF vectorizer (5000 features, bigrams)
2. Logistic Regression classifies into: DSA / OS / DBMS / CN / OOP / System Design
3. If confidence < 70%: escalates to Groq Llama 3.3-70B for higher accuracy
4. Circuit breaker: Groq failure → TF-IDF fallback always available

### Recommendation Engine (Module 3)

1. Skill scores → gap analysis (1.0 - proficiency, sorted by urgency)
2. Content-based filtering: match weak topics to curated 30-resource catalogue
3. Difficulty routing: score 0.0–0.35 → beginner, 0.35–0.60 → intermediate
4. Groq personalizes ordering with prerequisite reasoning and study schedule

---

## CI/CD Pipeline

```
Push to any branch
    ↓
┌──────────────┬────────────────┬──────────────────┐
│ Lint         │ Test           │ Security         │
│ ruff, eslint │ pytest (171)   │ bandit, pip-audit│
│ mypy, tsc    │ coverage ≥ 80% │ secret scanning  │
└──────────────┴────────────────┴──────────────────┘
    ↓ (all pass, push to main)
Docker build → tag with git SHA → push to ghcr.io
    ↓
Deploy to staging (auto)
    ↓ (tag v*.*.*)
Deploy to production (manual release)
```

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `SECRET_KEY` | ✓ | — | JWT signing key (32+ random bytes) |
| `GROQ_API_KEY` | ✓ | — | Free key from console.groq.com |
| `GROQ_MODEL` | | llama-3.3-70b-versatile | Groq model to use |
| `DATABASE_URL` | | postgres://devmentor:... | Async PostgreSQL DSN |
| `REDIS_URL` | | redis://redis:6379/0 | Redis connection URL |
| `ENVIRONMENT` | | development | development / production |
| `RATE_LIMIT_PER_MINUTE` | | 60 | Requests per minute per IP |

---

## Test Coverage

```
Backend (81 tests):
  test_auth.py              — JWT, bcrypt, register/login flow
  test_cache.py             — Redis patterns, TTL, sessions, denylist
  test_interview_service.py — Session lifecycle, ML scoring, EMA skill assessment
  test_observability.py     — Structured logging, Prometheus metrics, health checks

ML Service (90 tests):
  test_evaluator.py         — Cosine similarity, confidence scoring, grade assignment
  test_classifier.py        — TF-IDF training, Groq integration, circuit breaker
  test_recommender.py       — Gap computation, resource selection, Groq personalization
```

Run all tests: `make test`

---

## Deployment

### Local development

```bash
make setup   # One-time setup
make dev     # Start with hot reload
```

### Production (VPS / cloud VM)

```bash
# On your server
git clone https://github.com/your-username/devmentor-ai.git
cd devmentor-ai
cp .env.example .env
# Edit .env with production values and a strong SECRET_KEY

docker compose -f docker-compose.yml up -d
docker compose exec backend alembic upgrade head
```

For HTTPS, add Certbot/Let's Encrypt and update `nginx.conf` to listen on 443.

### GitHub Actions CD

Set these secrets in your repository (Settings → Secrets):

```
SECRET_KEY
GROQ_API_KEY
STAGING_HOST
STAGING_USER
STAGING_SSH_KEY
PRODUCTION_HOST
PRODUCTION_USER
PRODUCTION_SSH_KEY
```

Push a tag to deploy to production: `git tag v1.0.0 && git push --tags`

---

## Resume Impact

This project demonstrates:

- **Distributed systems design** — 6 containerized services with defined network boundaries
- **ML engineering** — Sentence Transformers, TF-IDF, cosine similarity, LLM orchestration
- **Production backend** — Async FastAPI, SQLAlchemy, Alembic migrations, JWT auth
- **Caching architecture** — Cache-aside pattern, write-invalidate, TTL selection
- **Observability** — Structured logging, Prometheus metrics, liveness/readiness probes
- **CI/CD** — GitHub Actions with quality gates, coverage enforcement, Docker SHA tagging
- **Security** — bcrypt, JWT, rate limiting, SQL injection prevention, non-root containers

---

*Built as a portfolio project demonstrating full-stack engineering, ML integration, and production operations.*
