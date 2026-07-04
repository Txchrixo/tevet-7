# Dockerfile — Tevet-7 Agentic Service (FastAPI backend)
#
# Build:
#   docker build -t tevet7-backend ./agentic-service
#
# Run:
#   docker run -p 8001:8001 --env-file ./agentic-service/.env tevet7-backend
#
# Health check:
#   curl http://localhost:8001/health

FROM python:3.12-slim

# Prevent Python from writing .pyc files and buffering stdout/stderr — both
# useful in containerized environments where logs go straight to docker logs.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first to leverage Docker's layer cache. Copying just
# requirements.txt means a code change does NOT invalidate the pip install
# layer, which is the slowest step in the build.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code.
COPY . .

# Expose the FastAPI port. The default uvicorn command binds to 0.0.0.0 so
# the service is reachable from outside the container.
EXPOSE 8001

# Run the ASGI app with uvicorn. In production we omit --reload (the source
# is baked into the image) and use a single worker — scale horizontally by
# running more containers behind a load balancer.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
