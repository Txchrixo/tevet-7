# Dockerfile — Tevet-7 Frontend (Next.js 16)
#
# Build:
#   docker build -t tevet7-frontend .
#
# Run:
#   docker run -p 3000:3000 \
#     --env AGENTIC_SERVICE_URL=http://tevet7-backend:8001 \
#     tevet7-frontend
#
# Health check (after startup):
#   curl http://localhost:3000/

FROM node:20-slim AS base

WORKDIR /app

# Copy the lockfiles first to leverage Docker's layer cache. The project
# uses bun.lock for dev, but the Docker image uses npm (which ships with
# node:20-slim and needs no extra install). npm install --frozen-lockfile
# uses the lockfile to produce deterministic installs.
COPY package.json bun.lock ./
RUN npm install --frozen-lockfile

# Copy the application source and build the Next.js standalone output.
COPY . .
RUN npm run build

# Expose the Next.js port. The default `next start` command binds to
# 0.0.0.0 so the app is reachable from outside the container.
EXPOSE 3000

CMD ["npm", "start"]
