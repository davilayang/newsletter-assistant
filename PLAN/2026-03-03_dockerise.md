# Plan: Dockerise newsletter-assistant

## Context

The newsletter-assistant has four runnable components (voice agent, scraping pipeline, NiceGUI frontend, Gmail MCP server). The goal is to package them into Docker images, wire them together for local development with docker-compose, and provide cloud-agnostic Kubernetes manifests that can be adapted to any provider later.

An earlier plan doc (`PLAN/2026-03-01_docker-k8s.md`) exists as a reference, but it contains stale details (references Streamlit/FastAPI instead of NiceGUI, wrong ports). This plan supersedes it.

---

## One Code Change Required

**`src/frontend/app.py`** — `host` is hardcoded to `127.0.0.1`, which prevents containers from accepting external connections:

```python
# BEFORE
ui.run(..., host="127.0.0.1", port=8080, ...)

# AFTER
ui.run(..., host="0.0.0.0", port=8080, ...)
```

---

## Docker Images

Three published images. No separate base image tag — base layer is shared via multi-stage build only.

| Image | Dockerfile | Purpose | Est. size |
|---|---|---|---|
| `newsletter-agent` | `docker/agent/Dockerfile` | LiveKit voice agent | ~800 MB |
| `newsletter-pipeline` | `docker/pipeline/Dockerfile` | Daily scraper + camoufox browser | ~2 GB |
| `newsletter-frontend` | `docker/frontend/Dockerfile` | NiceGUI web UI (port 8080) | ~800 MB |

The Gmail MCP server is **not containerised** — it runs via stdio from the host with `uv run`.

### Shared base layer (inline in agent + frontend Dockerfiles via multi-stage)

```dockerfile
FROM python:3.13-slim AS base
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
ENV PATH="/app/.venv/bin:$PATH"
```

### `docker/agent/Dockerfile`

- Multi-stage from base layer above
- Copies `src/`, `config/`
- `CMD ["python", "-m", "src.agent.agent"]`

### `docker/pipeline/Dockerfile`

Cannot reuse the base layer — needs extra system packages for the Firefox runtime:
- Installs browser shared libraries: `libglib2.0-0 libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2`
- Installs uv + project deps with `uv sync --frozen --no-dev --no-install-project`
- **Bakes camoufox binary at build time** so containers start without downloading (~300 MB browser):
  ```dockerfile
  RUN python -c "from camoufox.sync_api import Camoufox; Camoufox()"
  ```
- Copies `src/`, `config/`
- `CMD ["python", "-m", "src.knowledge.pipeline"]`

### `docker/frontend/Dockerfile`

- Multi-stage from base layer above
- Copies `src/`, `config/`
- `EXPOSE 8080`
- `CMD ["python", "-m", "src.frontend.app"]`

### `.dockerignore`

Excludes: `.venv/`, `.git/`, `data/`, `creds/`, `NOTES/`, `__pycache__/`, `*.pyc`, `.env`, `tests/`, `PLAN/`, `FINDINGS/`

---

## Local Development — `docker-compose.yml`

Agent and frontend start by default. Pipeline is profile-gated so it doesn't run every `docker compose up`.

```yaml
services:
  frontend:
    build: { context: ., dockerfile: docker/frontend/Dockerfile }
    ports: ["8080:8080"]
    env_file: .env
    volumes:
      - ./data:/app/data
      - ./creds:/app/creds
      - ./config:/app/config
      - ./NOTES:/app/NOTES

  agent:
    build: { context: ., dockerfile: docker/agent/Dockerfile }
    env_file: .env
    volumes:
      - ./data:/app/data
      - ./creds:/app/creds
      - ./config:/app/config
      - ./NOTES:/app/NOTES

  pipeline:
    build: { context: ., dockerfile: docker/pipeline/Dockerfile }
    env_file: .env
    volumes:
      - ./data:/app/data
      - ./creds:/app/creds
      - ./config:/app/config
    profiles: ["pipeline"]   # run with: docker compose --profile pipeline run pipeline
```

---

## Kubernetes Manifests — `k8s/`

```
k8s/
  namespace.yaml
  pvc.yaml                    # one shared ReadWriteOnce PVC (data + creds + NOTES)
  secret.yaml.template        # committed template; real secret.yaml is gitignored
  configmap.yaml              # newsletters.yaml + speech_replacements.yaml inlined
  agent/
    deployment.yaml
  pipeline/
    cronjob.yaml
  frontend/
    deployment.yaml
    service.yaml
    ingress.yaml              # TLS + host annotations left blank for provider-specific fill-in
  kustomization.yaml
```

### PVC design

Single `newsletter-data` PVC (ReadWriteOnce, 5 Gi). All three workloads mount the same volume:

| Mount path | Contents |
|---|---|
| `/app/data` | `articles.db` (SQLite) + `chroma/` (ChromaDB index) |
| `/app/creds` | `credentials.json`, `token.json`, `medium_auth.json` |
| `/app/NOTES` | Daily markdown notes written by agent |

> **ReadWriteOnce constraint:** all three pods must land on the same node. On a single-node cluster (k3s, minikube) this is automatic. On multi-node clusters, add a shared `nodeSelector` label to all three workloads.

### ConfigMap

Mounts `config/newsletters.yaml` and `config/speech_replacements.yaml` over `/app/config` at runtime. Newsletter config changes don't require an image rebuild — only a pod restart.

### Secret

`newsletter-env` secret provides all API keys via `envFrom.secretRef`. Real `k8s/secret.yaml` is gitignored; `k8s/secret.yaml.template` is committed with empty string values.

### Agent Deployment

- `replicas: 1`
- Scale to 0 when not in use to avoid LiveKit idle cost: `kubectl scale deploy/newsletter-agent --replicas=0 -n newsletter`

### Pipeline CronJob

- `schedule: "0 7 * * *"` (07:00 UTC — adjust per timezone)
- `restartPolicy: OnFailure`
- Manual trigger: `kubectl create job --from=cronjob/newsletter-pipeline pipeline-manual -n newsletter`

### Frontend Service + Ingress

- `ClusterIP` Service on port 8080
- Ingress with `# TODO: add provider-specific annotations` — user fills in cert-manager issuer, nginx class, etc.

### `.gitignore` additions

```
k8s/secret.yaml
```

---

## CI/CD — `.github/workflows/build-push.yml`

Trigger: push to `main`.
Steps:
1. Login to `ghcr.io` using `GITHUB_TOKEN`
2. Build + push all 3 images with tags `latest` and `sha-${{ github.sha }}`
3. (Optional deploy step) `kubectl apply -k k8s/` + rollout restart

---

## Files to Create / Modify

| File | Action |
|---|---|
| `src/frontend/app.py` | **Edit** — `host="127.0.0.1"` → `host="0.0.0.0"` |
| `.dockerignore` | **Create** |
| `docker/agent/Dockerfile` | **Create** |
| `docker/pipeline/Dockerfile` | **Create** |
| `docker/frontend/Dockerfile` | **Create** |
| `docker-compose.yml` | **Create** |
| `k8s/namespace.yaml` | **Create** |
| `k8s/pvc.yaml` | **Create** |
| `k8s/secret.yaml.template` | **Create** |
| `k8s/configmap.yaml` | **Create** (inline content from `config/*.yaml`) |
| `k8s/agent/deployment.yaml` | **Create** |
| `k8s/pipeline/cronjob.yaml` | **Create** |
| `k8s/frontend/deployment.yaml` | **Create** |
| `k8s/frontend/service.yaml` | **Create** |
| `k8s/frontend/ingress.yaml` | **Create** |
| `k8s/kustomization.yaml` | **Create** |
| `.gitignore` | **Edit** — append `k8s/secret.yaml` |
| `.github/workflows/build-push.yml` | **Create** |

---

## First-Time Cluster Setup

After applying manifests:
1. Bootstrap creds into the PVC via a debug pod:
   ```bash
   kubectl run creds-setup --image=busybox -it --rm \
     --overrides='{"spec":{"volumes":[{"name":"d","persistentVolumeClaim":{"claimName":"newsletter-data"}}],"containers":[{"name":"c","image":"busybox","command":["sh"],"volumeMounts":[{"name":"d","mountPath":"/mnt"}]}]}}' \
     -n newsletter
   # Then kubectl cp creds/ newsletter/creds-setup:/mnt/creds/
   ```
2. Scale up frontend + agent: `kubectl scale deploy/newsletter-frontend deploy/newsletter-agent --replicas=1 -n newsletter`
3. Trigger pipeline once manually (see CronJob section above)

---

## Verification

- **Local compose:** `docker compose up --build` → visit http://localhost:8080, verify UI, voice session
- **Pipeline:** `docker compose --profile pipeline run pipeline` → check `data/articles.db` populated
- **k8s local (k3d):** `k3d cluster create newsletter --port "8080:80@loadbalancer"` → `kubectl apply -k k8s/` → verify all pods Running
