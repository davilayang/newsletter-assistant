# Kubernetes Deployment

This guide covers deploying the newsletter assistant to a single-node k3s cluster on Hetzner Cloud. Sections are ordered by workflow:

1. **Provision** — create and secure the Hetzner server
2. **Bootstrap** — install k3s and fetch kubeconfig
3. **Build & Push** — build Docker images locally, push to Docker Hub
4. **Initial Setup** — install cert-manager, create secrets, deploy workloads
5. **Day-to-Day** — common operations for managing the cluster

## Prerequisites

- `docker` installed locally
- `kubectl` installed locally
- `hcloud` installed locally (Hetzner Cloud CLI)
  - Run `brew install hcloud` on MacOs
- A [Hetzner Project](https://console.hetzner.com/) 
- A [Docker Hub](https://hub.docker.com/) account

## Directory Structure

```
k8s/
  kustomization.yaml        # entry point — placeholders substituted via sed at deploy time
  namespace.yaml             # newsletter namespace
  pvc.yaml                   # 3 Gi ReadWriteOnce volume (data + creds + NOTES)
  secret.env.template        # copy to secret.env and fill in values (gitignored)
  agent/
    deployment.yaml          # LiveKit voice agent (1 replica)
  pipeline/
    cronjob.yaml             # not deployed — pipeline runs locally (see note below)
  cert-manager/
    cluster-issuer.yaml      # Let's Encrypt ACME issuer (ACME_EMAIL placeholder)
  frontend/
    deployment.yaml          # NiceGUI web UI
    service.yaml             # ClusterIP on port 80 → 8080
    ingress.yaml             # sslip.io host + TLS (SERVER_IP placeholder)
```
---

## Provision a Hetzner Cloud Server

You should have a default Project on the [Console](https://console.hetzner.com/projects).

> Get an API key from _Console → Project → Security → API Tokens_

### Server Setup

```bash
SSH_KEY_NAME="my-key"
SSH_PUB_KEY_FILE="~/.ssh/..."

# Authenticate CLI
hcloud context create newsletter
## Paste your API token when prompted

# Upload SSH Key
hcloud ssh-key create \
  --name $SSH_KEY_NAME --public-key-from-file $SSH_PUB_KEY_FILE

# Create a server
SERVER_NAME="newsletter-k3s"
hcloud server create --name $SERVER_NAME \
  --type cpx22 --image ubuntu-24.04 --location "hel1" \
  --ssh-key $SSH_KEY_NAME
## This config has "2 CPU, 4GB memory, 80GB storage"

# Get Server IP
hcloud server list
export SERVER_IP=<ipv4-from-output>
```

### Make it Secure with Firewall

An additional layer of protection to UFW inside the VM.

```bash
SERVER_NAME="newsletter-k3s"
FIREWALL_NAME="newsletter-fw"
MY_IP=$(curl -4 -s ifconfig.me)/32 # Current IP address

# Create firewall
hcloud firewall create --name $FIREWALL_NAME

## Restricted to Current IP only
hcloud firewall add-rule $FIREWALL_NAME \
  --direction in --protocol tcp --port 22 --source-ips ${MY_IP} # SSH
hcloud firewall add-rule $FIREWALL_NAME \
  --direction in --protocol tcp --port 6443 --source-ips ${MY_IP} # k3s API

## Public (frontend ingress)
hcloud firewall add-rule $FIREWALL_NAME \
  --direction in --protocol tcp --port 80 --source-ips 0.0.0.0/0 --source-ips ::/0
hcloud firewall add-rule $FIREWALL_NAME \
  --direction in --protocol tcp --port 443 --source-ips 0.0.0.0/0 --source-ips ::/0

# Apply to the Server
hcloud firewall apply-to-resource $FIREWALL_NAME --type server --server $SERVER_NAME
```

> Ports 8472/udp (flannel VXLAN) and 10250/tcp (kubelet metrics) are opened by UFW inside
> the VM but intentionally not exposed at the Hetzner firewall level on a single-node setup.


### Update Firewall After IP Change

If your local IP changes, update the SSH and k3s API firewall rules:

```bash
FIREWALL_NAME="newsletter-fw"
OLD_IP=...
NEW_IP=$(curl -4 -s ifconfig.me)/32 # Current IP address

# Update SSH rule
hcloud firewall delete-rule $FIREWALL_NAME \
  --direction in --protocol tcp --port 22 --source-ips $OLD_IP/32
hcloud firewall add-rule $FIREWALL_NAME \
  --direction in --protocol tcp --port 22 --source-ips $NEW_IP/32

# Update k3s API rule
hcloud firewall delete-rule $FIREWALL_NAME \
  --direction in --protocol tcp --port 6443 --source-ips $OLD_IP/32
hcloud firewall add-rule $FIREWALL_NAME \
  --direction in --protocol tcp --port 6443 --source-ips $NEW_IP/32
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
SERVER_IP=... # from `hclud server list`
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

# Test ssh working 
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
## Edit by replacing 127.0.0.1 with the Server IP
sed -i '' "s|127.0.0.1|${SERVER_IP}|" ~/.kube/newsletter-k3s.yaml

# Verify connectivity
kubectl --kubeconfig ~/.kube/newsletter-k3s.yaml get nodes

# Set alias
alias kh="kubectl --kubeconfig ~/.kube/newsletter-k3s.yaml"
kh get pods -A
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

---

## Initial Application Setup on K8S

### Install cert-manager

cert-manager handles automatic TLS certificate provisioning via Let's Encrypt.

```bash
CERT_MGR_YAML=https://github.com/cert-manager/cert-manager/releases/latest/download/cert-manager.yaml
kh apply -f $CERT_MGR_YAML

# Wait for cert-manager pods to be ready
kh wait --for=condition=Ready pods --all -n cert-manager --timeout=90s
```

### Create Docker Hub Pull Secret

Required for pulling private images from Docker Hub:

```bash
DOCKER_USER=...
DOCKER_TOKEN=...
kh create secret docker-registry dockerhub-creds \
  --docker-server=https://index.docker.io/v1/ \
  --docker-username=$DOCKER_USER \
  --docker-password=$DOCKER_TOKEN \
  -n newsletter
```

The secret `dockerhub-creds` is referenced via `imagePullSecrets` in all deployment manifests.

### Setup secrets file

```bash
cp k8s/secret.env.template k8s/secret.env
```

Fill in `k8s/secret.env` with your real API keys. This file is gitignored and never committed.

### Apply all configurations 

Creates the namespace, PVC, ConfigMap, Secret, ClusterIssuer, and all workloads in one command.

```bash
DOCKER_USER=your-dockerhub-username
SERVER_IP=your-server-ip-with-dashes  # E.g. 89-167-19-115 (dashes, not dots)
ACME_EMAIL=your-email@example.com     # For Let's Encrypt certificate notifications

kh kustomize --load-restrictor LoadRestrictionsNone k8s/ \
  | sed "s|docker.io/OWNER|docker.io/$DOCKER_USER|g" \
  | sed "s|SERVER_IP|$SERVER_IP|g" \
  | sed "s|ACME_EMAIL|$ACME_EMAIL|g" \
  | kh apply -f -
```

The frontend will be available at `https://<SERVER_IP>.sslip.io` (TLS via cert-manager + Let's Encrypt).

### Bootstrap credentials onto the PVC

Gmail OAuth tokens (`credentials.json`, `token.json`) and the Medium auth state (`medium_auth.json`) must be copied onto the PVC after it is created. 

```bash
# Start a temporary pod with the PVC mounted at /mnt.
# It sleeps for 5 minutes so you can copy files in from another terminal.
# The pod auto-deletes when it exits (--rm).
kh run bootstrap --image=busybox --rm -it \
  --overrides='{
    "spec": {
      "volumes": [{"name":"d","persistentVolumeClaim":{"claimName":"newsletter-data"}}],
      "containers": [{"name":"c","image":"busybox","command":["sleep","300"],
        "volumeMounts":[{"name":"d","mountPath":"/mnt"}]}]
    }
  }' -n newsletter

# In a separate terminal while the pod is running:
kubectl --kubeconfig ~/.kube/newsletter-k3s.yaml cp creds "newsletter/bootstrap":/mnt/

# Then Ctrl-C to terminate the pod
```

---

## Day-to-Day K8S Operations

### Rebuild and redeploy images

```bash
export DOCKER_USER=your-dockerhub-username

# Rebuild all, push, then restart
docker compose build && docker compose push
kh rollout restart deploy/newsletter-agent deploy/newsletter-frontend -n newsletter

# Or rebuild a single service
docker compose build agent && docker compose push agent
kh rollout restart deploy/newsletter-agent -n newsletter
```

### Check pod status

```bash
kh get pods -n newsletter
```

### View logs

```bash
kh logs -n newsletter deploy/newsletter-agent   -f
kh logs -n newsletter deploy/newsletter-frontend -f
```

### Scale agent up / down

Scale to 0 when not in use to avoid idle LiveKit costs:

```bash
kh scale deploy/newsletter-agent --replicas=0 -n newsletter
kh scale deploy/newsletter-agent --replicas=1 -n newsletter
```

### Run the Pipeline

The pipeline is **not deployed to k8s** — it runs locally via Docker Compose:

```bash
docker compose --profile pipeline run --rm pipeline
docker compose --profile pipeline run --rm pipeline index
```

Or directly with `uv`:

```bash
uv run poe pipeline
```

### Update Configs or Secrets config

Edit `config/newsletters.yaml` or `k8s/secret.env`, then re-apply:

```bash
kh kustomize --load-restrictor LoadRestrictionsNone k8s/ \
  | sed "s|docker.io/OWNER|docker.io/$DOCKER_USER|g" \
  | sed "s|SERVER_IP|$SERVER_IP|g" \
  | sed "s|ACME_EMAIL|$ACME_EMAIL|g" \
  | kh apply -f -
kh rollout restart deploy/newsletter-agent deploy/newsletter-frontend -n newsletter
```

---

## Multi-Node Clusters

The PVC uses `ReadWriteOnce` — all pods that mount it must be scheduled on the same node. On a single-node cluster (k3s, minikube) this is automatic.

On multi-node clusters, label one node and enable the nodeSelector in each manifest:

```bash
kh label node <node-name> newsletter=true
```

Then uncomment in `agent/deployment.yaml` and `frontend/deployment.yaml`:

```yaml
nodeSelector:
  newsletter: "true"
```

### Tear Down the Server

```bash
hcloud server delete newsletter-k3s
```
