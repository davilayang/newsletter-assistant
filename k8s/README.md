# Kubernetes Deployment

## Prerequisites

- `kubectl` connected to your cluster
- Docker Desktop installed locally (for building images)
- A [Docker Hub](https://hub.docker.com/) account
- A domain name pointed at your cluster's ingress IP (for the frontend)

---

## Provision a Hetzner Cloud Server

You should have a default Project on the [Console](https://console.hetzner.com/projects).

```bash
# Install CLI tool
brew install hcloud

# Get API Key from "Console → Project → Security → API Tokens"
# $HCLOUD_API_TOKEN
```

### Server Setup

```bash
# Authenticate CLI
hcloud context create newsletter
## Paste your API token when prompted

# Upload SSH Key
SSH_KEY_NAME="my-key"
SSH_PUB_KEY_FILE="~/.ssh/..."
hcloud ssh-key create \
  --name $SSH_KEY_NAME --public-key-from-file $SSH_PUB_KEY_FILE

# Create a server
## 2 CPU, 4GB memory, 80GB storage
SERVER_NAME="newsletter-k3s"
hcloud server create --name $SERVER_NAME \
  --type cpx22 --image ubuntu-24.04 --location "hel1" \
  --ssh-key $SSH_KEY_NAME

# Get IP
hcloud server list
export SERVER_IP=<ipv4-from-above>
```

### Make it Secure with Firewall

An additional layer of protection to UFW inside the VM.

```bash
SERVER_NAME="newsletter-k3s"
FIREWALL_NAME="newsletter-fw"
# Get my current IPv4 address
MY_IP=$(curl -4 -s ifconfig.me)/32

hcloud firewall create --name $FIREWALL_NAME

# Restricted to my IP only
hcloud firewall add-rule $FIREWALL_NAME \
  --direction in --protocol tcp --port 22 --source-ips ${MY_IP} # SSH
hcloud firewall add-rule $FIREWALL_NAME \
  --direction in --protocol tcp --port 6443 --source-ips ${MY_IP} # k3s API

# Public (frontend ingress)
hcloud firewall add-rule $FIREWALL_NAME \
  --direction in --protocol tcp --port 80 --source-ips 0.0.0.0/0 --source-ips ::/0
hcloud firewall add-rule $FIREWALL_NAME \
  --direction in --protocol tcp --port 443 --source-ips 0.0.0.0/0 --source-ips ::/0

hcloud firewall apply-to-resource $FIREWALL_NAME --type server --server $SERVER_NAME
```

> Ports 8472/udp (flannel VXLAN) and 10250/tcp (kubelet metrics) are opened by UFW inside
> the VM but intentionally not exposed at the Hetzner firewall level on a single-node setup.


```bash
FIREWALL_NAME="newsletter-fw"
OLD_IP=...
NEW_IP=...

# Remove old IP from rule
hcloud firewall delete-rule $FIREWALL_NAME \
  --direction in --protocol tcp --port 22 --source-ips $OLD_IP/32
# Add new IP to rule
hcloud firewall add-rule $FIREWALL_NAME \
  --direction in --protocol tcp --port 22 --source-ips $NEW_IP/32
```

## Bootstrap the Server with K3S

Run `scripts/bootstrap-k3s.sh` on the new server. It will:

- Create a non-root sudo user with your SSH key
- Harden SSH (disable root login + password auth)
- Configure UFW (ports 22, 6443, 8472/udp, 10250)
- Install fail2ban
- Install k3s (single node) with `--tls-san` for remote `kubectl` access
- Write a kubeconfig

```bash
SERVER_IP=... # hclud server list
SSH_KEY_FILE=...
SSH_PUB_KEY_FILE=...
DEPLOY_USER=deploy
DEPLOY_PASSWORD=...  # sudo password for the deploy user

# Copy and then run it as root
scp -i $SSH_KEY_FILE \
  scripts/bootstrap-k3s.sh root@${SERVER_IP}:/root/bootstrap-k3s.sh
ssh -i $SSH_KEY_FILE \
  root@${SERVER_IP} \
  "bash /root/bootstrap-k3s.sh ${DEPLOY_USER} '$(cat $SSH_PUB_KEY_FILE)' ${SERVER_IP} '${DEPLOY_PASSWORD}'"
```

> **Verify** you can SSH as `${DEPLOY_USER}` before closing the root session — the script
> disables root login on completion.

```bash
ssh -i $SSH_KEY_FILE \
  ${DEPLOY_USER}@${SERVER_IP} kubectl get nodes
```

### Fetch kubeconfig locally

k3s writes the kubeconfig to `/etc/rancher/k3s/k3s.yaml` with `127.0.0.1` as the server
address. Copy it and patch the address:

```bash
DEPLOY_USER=...
SERVER_IP=...
SSH_KEY_FILE=...
K3S_YAML=/etc/rancher/k3s/k3s.yaml

# Get Kubeconfig to Local
scp -i $SSH_KEY_FILE \
  ${DEPLOY_USER}@${SERVER_IP}:$K3S_YAML ~/.kube/newsletter-k3s.yaml

# Replace 127.0.0.1 with the Server IP
sed -i '' "s|127.0.0.1|${SERVER_IP}|" ~/.kube/newsletter-k3s.yaml

# Verify connectivity
kubectl --kubeconfig ~/.kube/newsletter-k3s.yaml get nodes
# Set alias
alias kh="kubectl --kubeconfig ~/.kube/newsletter-k3s.yaml"
kh get pods -A
```

### Tear down the Server

```bash
hcloud server delete newsletter-k3s
```

---

## Build & Push Images to Docker Hub

Images are built locally and pushed to Docker Hub. You can use either public or private repositories.

### Login to Docker Hub

```bash
docker login
# Enter your Docker Hub username and password/access token
```

### Build and push all images

The `docker-compose.yml` already defines the build contexts. Just set `DOCKER_USER` and use compose:

```bash
export DOCKER_USER=your-dockerhub-username

# Build all images
docker compose build

# Push all images
docker compose push

# Or build + push the pipeline (behind a profile)
docker compose --profile pipeline build
docker compose --profile pipeline push
```

### Using Private Docker Hub Repositories

You can make the Docker Hub repositories private (Settings → Make Private on each repo page).
K3s needs a registry secret to pull private images:

```bash
# Create the pull secret
kubectl create secret docker-registry dockerhub-creds \
  --docker-server=https://index.docker.io/v1/ \
  --docker-username=your-dockerhub-username \
  --docker-password=your-dockerhub-access-token \
  -n newsletter
```

Then add `imagePullSecrets` to each workload. In `agent/deployment.yaml`, `frontend/deployment.yaml`, and `pipeline/cronjob.yaml`, add under `spec.template.spec`:

```yaml
imagePullSecrets:
  - name: dockerhub-creds
```

---

## First-Time Setup

### 1. Set your Docker Hub username

Export `DOCKER_USER` — this is used at deploy time to substitute `OWNER` in `k8s/kustomization.yaml` without modifying the committed file:

```bash
export DOCKER_USER=your-dockerhub-username
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
kubectl kustomize k8s/ | sed "s|docker.io/OWNER|docker.io/$DOCKER_USER|g" | kubectl apply -f -
```

This creates the namespace, PVC, ConfigMap, Secret, and all workloads in one command. The `OWNER` placeholder in `kustomization.yaml` stays committed as-is.

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

### Rebuild and redeploy images

```bash
export DOCKER_USER=your-dockerhub-username

# Rebuild all, push, then restart
docker compose build && docker compose push
kubectl rollout restart deploy/newsletter-agent deploy/newsletter-frontend -n newsletter

# Or rebuild a single service
docker compose build agent && docker compose push agent
kubectl rollout restart deploy/newsletter-agent -n newsletter
```

### Check pod status

```bash
kubectl get pods -n newsletter
```

### View logs

```bash
kubectl logs -n newsletter deploy/newsletter-agent   -f
kubectl logs -n newsletter deploy/newsletter-frontend -f
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
kubectl kustomize k8s/ | sed "s|docker.io/OWNER|docker.io/$DOCKER_USER|g" | kubectl apply -f -
```

### Update secrets

Edit `k8s/secret.env`, then re-apply:

```bash
kubectl kustomize k8s/ | sed "s|docker.io/OWNER|docker.io/$DOCKER_USER|g" | kubectl apply -f -
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
  kustomization.yaml        # entry point — pipe through sed to substitute OWNER
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
