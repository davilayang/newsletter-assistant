# Kubernetes Deployment

> **TODO:** Integrate image builds with CI/CD (e.g. GitHub Actions) to automatically
> build and push `newsletter-agent`, `newsletter-pipeline`, and `newsletter-frontend`
> to `ghcr.io` on push to `main`, then trigger a rollout via `kubectl apply -k k8s/`.

## Prerequisites

- `kubectl` connected to your cluster
- Docker images built and pushed to `ghcr.io` (see [CI/CD](#cicd))
- A domain name pointed at your cluster's ingress IP (for the frontend)

---

## First-Time Setup

### 1. Set your image registry owner

Edit `k8s/kustomization.yaml` and replace `OWNER` with your GitHub username in the `images` section:

```yaml
images:
  - name: newsletter-agent
    newName: ghcr.io/your-username/newsletter-agent
  ...
```

### 2. Create the secrets file

```bash
cp k8s/secret.env.template k8s/secret.env
```

Fill in `k8s/secret.env` with your real API keys. This file is gitignored and never committed.

### 3. Set your domain

Edit `k8s/frontend/ingress.yaml` and replace `newsletter.yourdomain.com` with your actual domain. Uncomment the TLS and annotation blocks for your ingress controller (nginx / Traefik).

### 4. Deploy

```bash
kubectl apply -k k8s/
```

This creates the namespace, PVC, ConfigMap, Secret, and all workloads in one command.

### 5. Bootstrap credentials onto the PVC

Gmail OAuth tokens (`credentials.json`, `token.json`) and the Medium auth state (`medium_auth.json`) must be copied onto the PVC after it is created. Run a temporary pod to do this:

```bash
kubectl run bootstrap --image=busybox --rm -it \
  --overrides='{
    "spec": {
      "volumes": [{"name":"d","persistentVolumeClaim":{"claimName":"newsletter-data"}}],
      "containers": [{"name":"c","image":"busybox","command":["sh"],
        "volumeMounts":[{"name":"d","mountPath":"/mnt"}]}]
    }
  }' -n newsletter

# In a separate terminal while the pod is running:
kubectl cp creds/ newsletter/bootstrap:/mnt/creds/
```

---

## Day-to-Day Operations

### Check pod status

```bash
kubectl get pods -n newsletter
```

### View logs

```bash
kubectl logs -n newsletter deploy/newsletter-agent   -f
kubectl logs -n newsletter deploy/newsletter-frontend -f
kubectl logs -n newsletter -l job-name=newsletter-pipeline --tail=100
```

### Scale agent up / down

Scale to 0 when not in use to avoid idle LiveKit costs:

```bash
kubectl scale deploy/newsletter-agent --replicas=0 -n newsletter
kubectl scale deploy/newsletter-agent --replicas=1 -n newsletter
```

### Trigger the pipeline manually

```bash
kubectl create job --from=cronjob/newsletter-pipeline pipeline-manual -n newsletter
```

### Update newsletter config

Edit `config/newsletters.yaml` locally, then re-apply. Kustomize regenerates the ConfigMap and rolls the pods automatically:

```bash
kubectl apply -k k8s/
```

### Update secrets

Edit `k8s/secret.env`, then re-apply:

```bash
kubectl apply -k k8s/
kubectl rollout restart deploy/newsletter-agent deploy/newsletter-frontend -n newsletter
```

---

## Multi-Node Clusters

The PVC uses `ReadWriteOnce` — all pods that mount it must be scheduled on the same node. On a single-node cluster (k3s, minikube) this is automatic.

On multi-node clusters, label one node and enable the nodeSelector in each manifest:

```bash
kubectl label node <node-name> newsletter=true
```

Then uncomment in `agent/deployment.yaml`, `pipeline/cronjob.yaml`, and `frontend/deployment.yaml`:

```yaml
nodeSelector:
  newsletter: "true"
```

---

## Directory Structure

```
k8s/
  kustomization.yaml        # entry point — run: kubectl apply -k k8s/
  namespace.yaml
  pvc.yaml                  # 3 Gi ReadWriteOnce volume (data + creds + NOTES)
  secret.env.template       # copy to secret.env and fill in values
  agent/
    deployment.yaml
  pipeline/
    cronjob.yaml            # runs daily at 07:00 UTC
  frontend/
    deployment.yaml
    service.yaml
    ingress.yaml            # edit host + TLS annotations for your provider
```
