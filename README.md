# DealFlowTracker

VC-grade deal-flow management for early-stage investors.

## Quick Start

```bash
bash start.sh
# Backend:  http://localhost:8006
# Frontend: http://localhost:5178
# Demo login: demo@dealflow.dev / demo123
```

## Docker / fleet-net

DealFlowTracker ships a `docker-compose.yml` for the laptop-local fleet
network. Three containers (`dealflowtracker_postgres`,
`dealflowtracker_api`, `dealflowtracker_web`) on the shared `fleet-net`.

```bash
docker network create fleet-net 2>/dev/null || true
cp .env.example .env  # edit OPENAI_API_KEY + SECRET_KEY
docker compose up -d                                              # prod-like
docker compose -f docker-compose.yml -f docker-compose.dev.yml up # dev
```

Reach it at `http://localhost:8006/api/health` and
`http://localhost:5178/`. Fleet pattern reference:
[`/Users/donkeyking/development/infra/README.md`](/Users/donkeyking/development/infra/README.md).
