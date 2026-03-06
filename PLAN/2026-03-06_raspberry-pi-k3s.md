# Raspberry Pi K3s Deployment

Deploy the newsletter assistant to a Raspberry Pi (2 GB RAM) on the local network.

## Context

The current deployment targets a Hetzner cloud VPS (4 GB RAM, amd64) running k3s. A Raspberry Pi deployment needs:
- ARM64 Docker images (Pi 4/5 are aarch64)
- Tighter memory budget — 2 GB total, ~1.4 GB usable after OS + k3s overhead
- Local network access only (no public ingress, no cert-manager)
- No pipeline container (camoufox + Firefox is ~2 GB alone, too heavy for Pi)

## Phase 1 — Bootstrap the Raspberry Pi with K3s

### 1.1 Flash the OS

- Use Raspberry Pi Imager to flash **Ubuntu Server 24.04 LTS (64-bit)** or **Raspberry Pi OS Lite (64-bit)**
- Enable SSH and set hostname (e.g. `newsletter-pi`) during imaging
- Set a static IP via router DHCP reservation or `/etc/netplan/`

### 1.2 Harden the Pi

```bash
PI_IP=192.168.1.xxx
SSH_KEY_FILE=~/.ssh/id_ed25519

# Copy SSH key
ssh-copy-id -i $SSH_KEY_FILE pi@$PI_IP  # or ubuntu@$PI_IP

# Disable password auth
ssh pi@$PI_IP "sudo sed -i 's/^#PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config && sudo systemctl restart ssh"
```

### 1.3 Install K3s (memory-optimised)

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

### 1.4 Fetch kubeconfig locally

```bash
PI_IP=192.168.1.xxx
scp pi@$PI_IP:/etc/rancher/k3s/k3s.yaml ~/.kube/pi-k3s.yaml
sed -i '' "s|127.0.0.1|${PI_IP}|" ~/.kube/pi-k3s.yaml
alias kpi="kubectl --kubeconfig ~/.kube/pi-k3s.yaml"
kpi get nodes
```

## Phase 2 — Build ARM64 Images

The existing Dockerfiles work on ARM64 since they use `python:3.13-slim` (multi-arch). Build with `--platform`:

```bash
export DOCKER_USER=your-dockerhub-username

# Build ARM64 images (cross-compile from Mac or build natively on Pi)
docker compose build --build-arg PLATFORM=linux/arm64
docker compose push

# Or use buildx for cross-compilation from an amd64/Apple Silicon host
docker buildx build --platform linux/arm64 \
  -t $DOCKER_USER/newsletter-frontend:latest \
  -f docker/frontend/Dockerfile --push .

docker buildx build --platform linux/arm64 \
  -t $DOCKER_USER/newsletter-agent:latest \
  -f docker/agent/Dockerfile --push .
```

**Note:** On Apple Silicon Macs, `docker compose build` already produces `linux/arm64` images by default.

## Phase 3 — Deploy to the Pi

### 3.1 Adjust K8s resource limits for 2 GB

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

### 3.2 Frontend access via NodePort (no ingress)

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

### 3.3 Deploy

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

### 3.4 Access from local network

```
http://192.168.1.xxx:30080
```

No HTTPS needed on LAN — mic access works on `localhost` and can be enabled via `mkcert` if needed (see README "Mobile testing over local network" section).

## Phase 4 — Memory monitoring

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

## What NOT to deploy on the Pi

- **Pipeline container** — camoufox bundles Firefox (~2 GB image). Run the pipeline on your Mac or the Hetzner VPS and let the Pi serve the pre-built SQLite + ChromaDB data.
- **cert-manager** — unnecessary on LAN, saves ~60 MB.
- **Traefik / ingress controller** — NodePort is sufficient for LAN.

## Estimated memory budget

| Component | Memory |
|-----------|--------|
| OS + system services | ~400 MB |
| k3s (tuned) | ~300 MB |
| containerd + pods overhead | ~100 MB |
| frontend pod | 128–256 MB |
| agent pod | 256–512 MB |
| **Total** | **1.2–1.6 GB** |

Tight but workable. Scale agent to 0 when idle to stay comfortable.

## Implementation checklist

- [ ] Flash Pi with Ubuntu Server 24.04 64-bit, set static IP
- [ ] Harden SSH, install k3s with memory-saving flags
- [ ] Fetch kubeconfig locally
- [ ] Build ARM64 images (or rely on Apple Silicon native builds)
- [ ] Create `k8s/overlays/pi/` with resource patches + NodePort service
- [ ] Deploy and bootstrap credentials
- [ ] Verify access at `http://<PI_IP>:30080`
- [ ] Test voice session from phone on same LAN
