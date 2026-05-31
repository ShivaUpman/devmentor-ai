# DevMentor AI

Adaptive AI-powered developer interview platform that evaluates technical answers, identifies skill gaps, and generates personalized learning roadmaps.

Built with FastAPI, Next.js, PostgreSQL, Redis, Sentence Transformers, and Groq.

---

## Features

### Adaptive Technical Interviews

* Dynamically adjusts question difficulty based on candidate performance
* Prioritizes weak skill areas for targeted improvement
* Prevents repeated questions within a session
* Tracks skill progression across interview attempts

### AI-Powered Evaluation

* Semantic answer scoring using Sentence Transformers
* Confidence and quality assessment
* Personalized coaching feedback
* Skill-level tracking by topic

### Personalized Learning Roadmaps

* Identifies knowledge gaps
* Recommends curated learning resources
* Generates personalized improvement paths
* Tracks completed learning milestones

### AI Code Review

* Automated code review assistance
* Quality and improvement suggestions
* Feedback tailored to developer skill level

---

## Screenshots

### Dashboard
<img width="958" height="443" alt="{47A80D36-A5C9-4DC8-99FD-E6A534C80C8E}" src="https://github.com/user-attachments/assets/172f29df-3110-407f-b334-28107c27e1c4" />

### Adaptive Interview
<img width="953" height="442" alt="{2B13D935-6750-4A40-83CA-88822358B648}" src="https://github.com/user-attachments/assets/cf849b16-4fbf-4883-93d8-3c98228e7edf" />

### Learning Roadmap
<img width="952" height="441" alt="{59891FB8-207E-43CB-AC29-868FF0957543}" src="https://github.com/user-attachments/assets/40f44706-3fb0-4ba4-8679-c7dfde2146f3" />




## Architecture

```text
                   ┌─────────────┐
                   │   Nginx     │
                   │Reverse Proxy│
                   └──────┬──────┘
                          │
          ┌───────────────┼───────────────┐
          │                               │
          ▼                               ▼
    Next.js Frontend               FastAPI Backend
        (3000)                          (8000)
                                           │
                  ┌────────────────────────┼───────────────────────┐
                  │                        │                       │
                  ▼                        ▼                       ▼
             PostgreSQL                 Redis                ML Service
               (5432)                  (6379)                 (8001)
                                                               │
                                    ┌──────────────────────────┼────────────────────┐
                                    │                          │                    │
                                    ▼                          ▼                    ▼
                        Sentence Transformers          TF-IDF Classifier      Groq LLM
```

---

## Adaptive Interview Flow

1. Candidate starts an interview session.
2. Initial questions are selected based on the chosen topic.
3. Each answer is evaluated using semantic similarity and confidence scoring.
4. Skill scores are updated after every response.
5. Future questions are selected dynamically:

   * Strong performance → higher difficulty
   * Weak performance → targeted reinforcement
6. Final reports summarize strengths, weaknesses, and learning recommendations.

---

## Tech Stack

| Layer          | Technology                   |
| -------------- | ---------------------------- |
| Frontend       | Next.js, TypeScript          |
| Backend        | FastAPI, Python 3.11         |
| Database       | PostgreSQL                   |
| Cache          | Redis                        |
| Authentication | JWT, bcrypt                  |
| ML Evaluation  | Sentence Transformers        |
| Classification | TF-IDF + Logistic Regression |
| LLM Feedback   | Groq Llama 3                 |
| Containers     | Docker, Docker Compose       |
| CI/CD          | GitHub Actions               |
| Monitoring     | Prometheus Metrics           |

---

## Project Structure

```text
devmentor-ai/
├── backend/          # FastAPI API
├── frontend/         # Next.js application
├── ml/               # ML services
├── nginx/            # Reverse proxy
├── .github/          # CI/CD workflows
├── docker-compose.yml
└── README.md
```

## Quick Start

### Prerequisites

* Docker
* Docker Compose
* Groq API Key

### Clone Repository

```bash
git clone https://github.com/ShivaUpman/devmentor-ai.git
cd devmentor-ai
cp .env.example .env
```

### Configure Environment

Add your Groq API key to `.env`:

```env
GROQ_API_KEY=your_key_here
```

Generate a secure secret key:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Add the generated value to:

```env
SECRET_KEY=generated_secret_key
```

### Start Application

```bash
docker compose up --build
```

### Access Services

| Service      | URL                      |
| ------------ | ------------------------ |
| Application  | http://localhost         |
| API Docs     | http://localhost/docs    |
| Health Check | http://localhost/health  |
| Metrics      | http://localhost/metrics |

---

## API Reference

### Authentication

```http
POST /api/v1/auth/register
POST /api/v1/auth/login
POST /api/v1/auth/refresh
GET  /api/v1/auth/me
POST /api/v1/auth/logout
```

### Interview Sessions

```http
POST /api/v1/interview/
GET  /api/v1/interview/
GET  /api/v1/interview/{id}

GET  /api/v1/interview/{id}/questions
POST /api/v1/interview/{id}/questions/next

POST /api/v1/interview/questions/{id}/submit
POST /api/v1/interview/{id}/complete

GET  /api/v1/interview/{id}/results
```

### Roadmaps

```http
GET   /api/v1/roadmap/skills
GET   /api/v1/roadmap/roadmap
PATCH /api/v1/roadmap/roadmap/{id}
```

### Code Review

```http
POST /api/v1/code-review/
```

### Monitoring

```http
GET /health
GET /health/ready
GET /metrics
```

---

## Machine Learning Pipeline

### Answer Evaluation

1. Candidate answer and ideal answer are encoded using Sentence Transformers.
2. Embeddings are compared using cosine similarity.
3. Confidence metrics are calculated.
4. Scores are combined into a final evaluation.
5. Groq generates personalized coaching feedback.

### Skill Classification

1. Question text is vectorized using TF-IDF.
2. Logistic Regression predicts the topic:

   * DSA
   * Operating Systems
   * DBMS
   * Computer Networks
   * OOP
   * System Design
3. Low-confidence predictions can be escalated to Groq for validation.

### Recommendation Engine

1. Skill scores identify knowledge gaps.
2. Resources are matched to weak topics.
3. Recommendations are ranked by relevance and difficulty.
4. Learning roadmaps are generated.

---

## Testing

Run all tests:

```bash
make test
```

Backend tests:

```bash
make test-backend
```

ML service tests:

```bash
make test-ml
```

Linting:

```bash
make lint
```

Health checks:

```bash
make health
```

---

## Development Commands

```bash
make help
make setup
make dev
make test
make lint
make migrate
make logs
make clean
```

---

## Deployment

### Local Development

```bash
make setup
make dev
```

### Production Deployment

```bash
git clone https://github.com/ShivaUpman/devmentor-ai.git

cd devmentor-ai

cp .env.example .env

docker compose up -d

docker compose exec backend alembic upgrade head
```

---

## Environment Variables

| Variable              | Description                  |
| --------------------- | ---------------------------- |
| SECRET_KEY            | JWT signing key              |
| GROQ_API_KEY          | Groq API key                 |
| GROQ_MODEL            | Model name                   |
| DATABASE_URL          | PostgreSQL connection string |
| REDIS_URL             | Redis connection string      |
| ENVIRONMENT           | development or production    |
| RATE_LIMIT_PER_MINUTE | API rate limit               |

---

## Key Engineering Concepts

* Adaptive assessment systems
* Semantic answer evaluation
* Recommendation engines
* JWT authentication
* Redis caching
* Dockerized microservices
* FastAPI backend architecture
* CI/CD pipelines
* ML-powered feedback generation

---

## Future Improvements

* Voice-based interview sessions
* Real-time analytics dashboard
* Multi-language interview support
* Team and recruiter dashboards
* Advanced skill progression tracking

---

## License

This project is licensed under the MIT License.

---
