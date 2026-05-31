# ── Stage 1: base ────────────────────────────────────────────────────────────
# WHY python:3.11-slim?
#   - "slim" strips dev tools, docs, and test files → smaller image (~55MB vs ~900MB full)
#   - Smaller image = faster pulls, less attack surface, lower storage costs
#   - Interview question: "What is a multi-stage build and why use it?"
FROM python:3.11-slim AS base

# WHY set PYTHONDONTWRITEBYTECODE and PYTHONUNBUFFERED?
#   - PYTHONDONTWRITEBYTECODE: don't create .pyc files (useless in containers)
#   - PYTHONUNBUFFERED: print() and logging output appears in docker logs immediately
#     without this, logs are buffered and you won't see crashes in real time
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# WHY /app as WORKDIR?
#   - Industry convention. Sets all relative paths from here.
#   - Avoids accidentally writing to / and polluting the container root
WORKDIR /app

# ── Stage 2: dependencies ─────────────────────────────────────────────────────
# WHY copy requirements BEFORE copying app code?
#   CRITICAL performance trick: Docker caches each layer.
#   If you copy all code first, then pip install — any code change busts the
#   pip cache and re-installs everything. Copying requirements.txt first means
#   Docker only re-runs pip install when requirements actually change.
COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ── Stage 3: app ──────────────────────────────────────────────────────────────
# Now copy the actual application code
COPY . .

# WHY create a non-root user?
#   Security best practice. Running as root inside a container means a container
#   escape vulnerability gives the attacker root on the host. FAANG-level answer.
RUN adduser --disabled-password --no-create-home appuser
USER appuser

# WHY EXPOSE 8000?
#   Documentation only — tells Docker which port the app listens on.
#   The actual port binding happens in docker-compose.yml with "ports:"
EXPOSE 8000

# WHY use uvicorn with --host 0.0.0.0?
#   By default uvicorn binds to 127.0.0.1 (localhost).
#   Inside a container, localhost only reaches the container itself.
#   0.0.0.0 means "accept connections on any network interface" — required
#   so Nginx (in a different container) can reach the FastAPI container.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
