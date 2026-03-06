# K8s Deployment Hardening Plan — 2026-03-04

Based on review findings in `FINDINGS/2026-03-04_k8s-deployment-review.md`.

---

## Phase 1: Resource & Reliability (High Impact, Low Risk)

### 1.1 Add CPU limits to all deployments

| File | CPU Limit |
|------|-----------|
| `k8s/agent/deployment.yaml` | 500m |
| `k8s/frontend/deployment.yaml` | 500m |
| `k8s/pipeline/cronjob.yaml` | 2000m |

### 1.2 Add liveness/readiness probes

**Frontend** (`k8s/frontend/deployment.yaml`):
- Readiness: `httpGet /` port 8080, initialDelay 10s, period 5s
- Liveness: `httpGet /` port 8080, initialDelay 30s, period 10s

**Agent** (`k8s/agent/deployment.yaml`):
- Liveness: `tcpSocket` on the agent's port or an exec-based check
- May need a health endpoint added to `src/agent/agent.py`

### 1.3 Add `imagePullPolicy: Always` to all containers

Since all images use `latest` tag in `kustomization.yaml`.

### 1.4 Pipeline CronJob tuning

- Add `backoffLimit: 3`
- Add `startingDeadlineSeconds: 300`

---

## Phase 2: Security Hardening

### 2.1 Add SecurityContext to all deployments

```yaml
securityContext:
  runAsNonRoot: true
  runAsUser: 1000
  fsGroup: 1000
  capabilities:
    drop: ["ALL"]
```

### 2.2 Update Dockerfiles to run as non-root

Add to each Dockerfile:
```dockerfile
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser
```

**Files:**
- `docker/agent.Dockerfile`
- `docker/pipeline.Dockerfile`
- `docker/frontend.Dockerfile`

> **Note:** Pipeline Dockerfile may need special handling — camoufox/Firefox may require specific permissions.

### 2.3 Add imagePullSecrets (if ghcr.io images are private)

Create a `ghcr-login` secret and reference it in all deployments:
```yaml
imagePullSecrets:
  - name: ghcr-login
```

---

## Phase 3: Ingress & TLS

### 3.1 Configure TLS on ingress

- Uncomment TLS annotations in `k8s/frontend/ingress.yaml`
- Choose approach: cert-manager with Let's Encrypt (recommended) or manual certs
- k3s ships with Traefik — use Traefik-specific annotations

### 3.2 Install cert-manager (if using Let's Encrypt)

```bash
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/latest/download/cert-manager.yaml
```

Create a ClusterIssuer for Let's Encrypt and reference it in the ingress.

---

## Phase 4: Future Improvements (Low Priority)

- [ ] Add ServiceAccount + RBAC with minimal permissions
- [ ] Add NetworkPolicies to restrict pod-to-pod traffic
- [ ] Add PodDisruptionBudgets for agent + frontend
- [ ] Move from `latest` tags to versioned tags (commit SHA or semver)
- [ ] Consider Sealed Secrets or External Secrets Operator for secret management

---

## Execution Order

1. Phase 1 first — immediate reliability wins, no breaking changes
2. Phase 2 requires Dockerfile rebuilds — do alongside next image push
3. Phase 3 when domain is pointed at the cluster
4. Phase 4 as needed
