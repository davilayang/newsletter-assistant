# Raspberry Pi Deployment

Deploy the newsletter assistant to a Raspberry Pi (2 GB RAM) on the local network.

Two deployment options are available — **Docker Compose** (lighter) or **K3s** (Kubernetes). Choose based on your needs.

## Context

The current deployment targets a Hetzner cloud VPS (4 GB RAM, amd64) running k3s. A Raspberry Pi deployment needs:
- ARM64 Docker images (Pi 4/5 are aarch64)
- Tighter memory budget — 2 GB total
- Local network access only (no public ingress, no cert-manager)
- No pipeline container (camoufox + Firefox is ~2 GB alone, too heavy for Pi)

## Comparison: Docker Compose vs K3s

| | Docker Compose | K3s |
|---|---|---|
| Orchestration overhead | ~80 MB (Docker daemon) | ~400 MB (k3s + containerd) |
| Usable for app | ~1.5 GB | ~1.1 GB |
| Estimated total usage | ~0.9–1.2 GB | ~1.2–1.6 GB |
| Headroom on 2 GB | ~800 MB–1.1 GB | ~400–800 MB |
| Complexity | Low — single `docker compose up` | Medium — kubeconfig, kustomize overlays |
| Rolling updates | `docker compose pull && up -d` | `kubectl rollout restart` |
| Health checks | Docker built-in | K8s liveness/readiness probes |
| Best for | Simple single-node, tight memory | Multi-node future, K8s ecosystem |

**Recommendation:** Docker Compose for 2 GB Pi — saves ~300 MB of orchestration overhead.

## Prerequisites (both options)

### Flash the OS

- Use Raspberry Pi Imager to flash **Ubuntu Server 24.04 LTS (64-bit)** or **Raspberry Pi OS Lite (64-bit)**
- Enable SSH and set hostname (e.g. `newsletter-pi`) during imaging
- Set a static IP via router DHCP reservation or `/etc/netplan/`

### Harden the Pi

```bash
PI_IP=192.168.1.xxx
SSH_KEY_FILE=~/.ssh/id_ed25519

# Copy SSH key
ssh-copy-id -i $SSH_KEY_FILE pi@$PI_IP  # or ubuntu@$PI_IP

# Disable password auth
ssh pi@$PI_IP "sudo sed -i 's/^#PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config && sudo systemctl restart ssh"
```

### Build ARM64 Images (on your Mac, transfer to Pi)

Build locally on your Mac (fast) and transfer images to the Pi via `docker save` / `docker load` — no Docker Hub needed.

```bash
# Build ARM64 images on your Mac (Apple Silicon produces arm64 natively)
docker compose build frontend agent

# Export images to tarballs
docker save ${DOCKER_USER}/newsletter-frontend:latest | gzip > /tmp/frontend.tar.gz
docker save ${DOCKER_USER}/newsletter-agent:latest | gzip > /tmp/agent.tar.gz

# Transfer to Pi and load
PI_IP=192.168.1.xxx
scp /tmp/frontend.tar.gz /tmp/agent.tar.gz pi@$PI_IP:/tmp/

ssh pi@$PI_IP "gunzip -c /tmp/frontend.tar.gz | docker load && \
               gunzip -c /tmp/agent.tar.gz | docker load && \
               rm /tmp/frontend.tar.gz /tmp/agent.tar.gz"
```

**Note:** On Apple Silicon Macs, `docker compose build` produces `linux/arm64` images by default — no `--platform` flag needed.

---

## Option A: Docker Compose (Recommended for 2 GB Pi)

### A.1 Install Docker Engine on the Pi

Install Docker Engine (not Docker Desktop) — it's much lighter:

```bash
ssh pi@$PI_IP

# Install Docker Engine via official script
curl -fsSL https://get.docker.com | sh

# Add your user to the docker group
sudo usermod -aG docker $USER

# Install Docker Compose plugin
sudo apt-get install -y docker-compose-plugin

# Verify
docker --version
docker compose version
```

### A.2 Pi-specific Compose override

A `docker-compose.pi.yml` override file is provided at the project root. It:
- Excludes the pipeline service entirely (empty service definition overrides the base)
- Adds memory limits: 256 MB for frontend, 512 MB for agent
- Switches agent to production mode (not dev)
- Binds frontend to port 8080 on all interfaces

### A.3 Deploy to the Pi

```bash
PI_IP=192.168.1.xxx

# Copy the project to the Pi
rsync -avz --exclude '.git' --exclude 'data/' --exclude '__pycache__' \
  . pi@$PI_IP:~/newsletter-assistant/

# Copy credentials and env file
scp .env pi@$PI_IP:~/newsletter-assistant/.env
scp -r creds pi@$PI_IP:~/newsletter-assistant/creds/

# SSH in and start (images already loaded via docker save/load)
ssh pi@$PI_IP
cd ~/newsletter-assistant

docker compose -f docker-compose.yml -f docker-compose.pi.yml up -d
```

### A.4 Access from local network

```
http://192.168.1.xxx:8080
```

No HTTPS needed on LAN — mic access works on `localhost` and can be enabled via `mkcert` if needed.

### A.5 Monitoring

```bash
# Real-time resource usage
docker stats

# View logs
docker compose -f docker-compose.yml -f docker-compose.pi.yml logs -f

# Restart after config changes
docker compose -f docker-compose.yml -f docker-compose.pi.yml up -d --force-recreate
```

If the agent is too heavy, stop it when not in use:

```bash
docker compose -f docker-compose.yml -f docker-compose.pi.yml stop agent
# Restart when needed:
docker compose -f docker-compose.yml -f docker-compose.pi.yml start agent
```

### A.6 Teardown

SSH into the Pi first, then run `down`:

```bash
ssh pi@$PI_IP
cd ~/newsletter-assistant

# Stop and remove containers + network
docker compose -f docker-compose.yml -f docker-compose.pi.yml down

# Also remove built images to free disk space
docker compose -f docker-compose.yml -f docker-compose.pi.yml down --rmi all

# Nuclear option: remove everything including volumes (deletes data!)
docker compose -f docker-compose.yml -f docker-compose.pi.yml down --rmi all --volumes
```

`down` stops containers and removes the network. Data in `./data/`, `./creds/`, etc. is bind-mounted from the host filesystem, so it survives `down` — even with `--volumes` (which only removes named Docker volumes, not bind mounts).

### Memory budget (Docker Compose)

| Component | Memory |
|-----------|--------|
| OS + system services | ~400 MB |
| Docker daemon | ~80 MB |
| frontend container | 128–256 MB |
| agent container | 256–512 MB |
| **Total** | **~0.9–1.2 GB** |

Comfortable on 2 GB with ~800 MB–1.1 GB headroom.

---

## Option B: K3s

### B.1 Install K3s (memory-optimised)

K3s defaults use ~500 MB RAM. Reduce with these flags:

```bash
ssh pi@$PI_IP

# Install k3s with memory-saving flags
curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="\
  --disable traefik \
  --disable servicelb \
  --disable metrics-server \
  --kubelet-arg=max-pods=20 \
  --kubelet-arg=eviction-hard=memory.available<128Mi \
  --kubelet-arg=system-reserved=memory=256Mi \
  " sh -

# Verify
sudo kubectl get nodes
```

**Why disable these components:**
- `traefik` — saves ~80 MB; use a NodePort service instead for LAN access
- `servicelb` — saves ~30 MB; not needed without LoadBalancer services
- `metrics-server` — saves ~40 MB; not needed for single-node personal use
- `system-reserved` — reserves 256 MB for OS, preventing k8s from starving the system
- `eviction-hard` — starts evicting pods when available memory drops below 128 MB

Expected k3s overhead after tuning: **~300 MB** (vs ~500 MB default).

### B.2 Fetch kubeconfig locally

```bash
PI_IP=192.168.1.xxx
scp pi@$PI_IP:/etc/rancher/k3s/k3s.yaml ~/.kube/pi-k3s.yaml
sed -i '' "s|127.0.0.1|${PI_IP}|" ~/.kube/pi-k3s.yaml
alias kpi="kubectl --kubeconfig ~/.kube/pi-k3s.yaml"
kpi get nodes
```

### B.3 Adjust K8s resource limits for 2 GB

Current limits (Hetzner 4 GB):
| Container | Request | Limit |
|-----------|---------|-------|
| frontend  | 256 Mi  | 512 Mi |
| agent     | 512 Mi  | 1 Gi   |
| **total** | **768 Mi** | **1.5 Gi** |

Pi-adjusted limits (2 GB, ~1.4 GB usable, ~1.1 GB for pods):
| Container | Request | Limit |
|-----------|---------|-------|
| frontend  | 128 Mi  | 256 Mi |
| agent     | 256 Mi  | 512 Mi |
| **total** | **384 Mi** | **768 Mi** |

Create a kustomize overlay at `k8s/overlays/pi/`:

```
k8s/overlays/pi/
  kustomization.yaml        # patches resource limits + disables ingress
  resource-patches.yaml     # lower memory limits
  frontend-nodeport.yaml    # NodePort service for LAN access
```

### B.4 Frontend access via NodePort (no ingress)

Without Traefik, expose the frontend directly via NodePort:

```yaml
# k8s/overlays/pi/frontend-nodeport.yaml
apiVersion: v1
kind: Service
metadata:
  name: newsletter-frontend
  namespace: newsletter
spec:
  type: NodePort
  selector:
    app: newsletter-frontend
  ports:
    - port: 8080
      targetPort: 8080
      nodePort: 30080   # access at http://<PI_IP>:30080
```

### B.5 Deploy

```bash
PI_IP=192.168.1.xxx

# Create namespace + secrets (same as Hetzner flow)
kpi apply -f k8s/namespace.yaml
cp k8s/secret.env.template k8s/secret.env  # fill in API keys
kpi create secret generic newsletter-env \
  --from-env-file=k8s/secret.env -n newsletter

# Apply Pi overlay
kpi apply -k k8s/overlays/pi/

# Bootstrap credentials onto PVC (same debug pod method)
kpi run bootstrap --image=busybox --rm -it \
  --overrides='{"spec":{"volumes":[{"name":"d","persistentVolumeClaim":{"claimName":"newsletter-data"}}],"containers":[{"name":"c","image":"busybox","command":["sleep","300"],"volumeMounts":[{"name":"d","mountPath":"/mnt"}]}]}}' \
  -n newsletter

# In another terminal:
kpi cp creds "newsletter/bootstrap":/mnt/
```

### B.6 Access from local network

```
http://192.168.1.xxx:30080
```

No HTTPS needed on LAN — mic access works on `localhost` and can be enabled via `mkcert` if needed.

### B.7 Memory monitoring

With only ~300 MB headroom, monitor memory pressure:

```bash
# Real-time node memory
kpi top node

# Pod memory usage
kpi top pods -n newsletter

# Check for OOM kills
kpi get events -n newsletter --field-selector reason=OOMKilling
```

If the agent is too heavy, scale it to 0 when not in use:

```bash
kpi scale deploy/newsletter-agent --replicas=0 -n newsletter
```

This frees ~256–512 MB. Scale back up when needed for voice sessions.

### Memory budget (K3s)

| Component | Memory |
|-----------|--------|
| OS + system services | ~400 MB |
| k3s (tuned) | ~300 MB |
| containerd + pods overhead | ~100 MB |
| frontend pod | 128–256 MB |
| agent pod | 256–512 MB |
| **Total** | **~1.2–1.6 GB** |

Tight but workable. Scale agent to 0 when idle to stay comfortable.

---

## What NOT to deploy on the Pi

- **Pipeline container** — camoufox bundles Firefox (~2 GB image). Run the pipeline on your Mac or the Hetzner VPS and let the Pi serve the pre-built SQLite + ChromaDB data.
- **cert-manager** — unnecessary on LAN, saves ~60 MB.
- **Traefik / ingress controller** — NodePort (K3s) or direct port binding (Compose) is sufficient for LAN.

## Implementation checklist

### Option A: Docker Compose
- [ ] Flash Pi with Ubuntu Server 24.04 64-bit, set static IP
- [ ] Harden SSH
- [ ] Install Docker Engine + Compose plugin
- [ ] Build ARM64 images on Mac, `docker save | scp | docker load` to Pi
- [ ] `rsync` project + credentials to Pi
- [ ] `docker compose -f docker-compose.yml -f docker-compose.pi.yml up -d`
- [ ] Verify access at `http://<PI_IP>:8080`
- [ ] Test voice session from phone on same LAN

### Option B: K3s
- [ ] Flash Pi with Ubuntu Server 24.04 64-bit, set static IP
- [ ] Harden SSH, install k3s with memory-saving flags
- [ ] Fetch kubeconfig locally
- [ ] Build ARM64 images (or rely on Apple Silicon native builds)
- [ ] Create `k8s/overlays/pi/` with resource patches + NodePort service
- [ ] Deploy and bootstrap credentials
- [ ] Verify access at `http://<PI_IP>:30080`
- [ ] Test voice session from phone on same LAN
