# Simplified Pi Deployment

Three steps: build on Mac, rsync creds, docker compose up on Pi.

**Prerequisite:** Docker Engine + Compose plugin already installed on Pi, SSH access working.

### Enable cgroup memory limits (one-time)

Docker memory limits require cgroup memory support enabled in the kernel. Without this, `deploy.resources.limits.memory` in `docker-compose.pi.yml` is silently ignored.

```bash
# Append to kernel cmdline (must stay on one line)
# Ubuntu Server: /boot/firmware/cmdline.txt
# Raspberry Pi OS: /boot/cmdline.txt
ssh $PI "echo ' cgroup_enable=memory cgroup_memory=1' | sudo tee -a /boot/firmware/cmdline.txt && sudo reboot"
```

### Enable HTTPS for mic access (one-time)

Browsers block `getUserMedia()` (microphone) on non-localhost HTTP. Use `mkcert` to create a trusted local CA + cert.

```bash
# On Mac — install mkcert and create a local CA
brew install mkcert

# Generate cert for the Pi's IP (or hostname)
mkcert -cert-file creds/pi-cert.pem -key-file creds/pi-key.pem 192.168.1.168

# Copy certs to Pi
# rsync -avz pi-cert.pem pi-key.pem $PI:~/newsletter-assistant/creds/

# Trust the CA on your other devices (phone, etc.):
#   Copy ~/Library/Application\ Support/mkcert/rootCA.pem to the device
#   iOS: Settings → Profile Downloaded → Install → Settings → General → About → Certificate Trust Settings → enable
#   Android: Settings → Security → Install from storage
```

Add these to `.env` on the Pi (certs are already volume-mounted at `/app/creds`):

```
SSL_CERTFILE=/app/creds/pi-cert.pem
SSL_KEYFILE=/app/creds/pi-key.pem
```

Then access at `https://<PI_IP>:8080`.

```bash
PI=pi@192.168.1.xxx
```

## 1. Build images on Mac & transfer to Pi

```bash
PI=... # e.g. user@raspberry-pi-ip
PI_IP=192.168.1.168
# Build (Apple Silicon = arm64 natively)
docker compose build frontend agent

# Faster alternative: netcat (no SSH encryption overhead)
# On Pi — start listeners:
#   nc -l -p 9998 | docker load
#   nc -l -p 9999 | docker load
# On Mac:
docker save local/newsletter-frontend:latest | nc $PI_IP 9998
docker save local/newsletter-agent:latest    | nc $PI_IP 9999

# Save, transfer, load (via SSH)
docker save local/newsletter-frontend:latest | gzip | ssh $PI "gunzip | docker load"
docker save local/newsletter-agent:latest    | gzip | ssh $PI "gunzip | docker load"

```

## 2. Rsync credentials to Pi

```bash
PI=... # e.g. user@raspberry-pi-ip
# Create project dir on Pi
ssh $PI "mkdir -p ~/newsletter-assistant"

# Only send what's needed to run (no source code — it's baked into images)
rsync -avz .env                    $PI:~/newsletter-assistant/
rsync -avz creds/                  $PI:~/newsletter-assistant/creds/
rsync -avz config/                 $PI:~/newsletter-assistant/config/
rsync -avz docker-compose.yml      $PI:~/newsletter-assistant/
rsync -avz docker-compose.pi.yml   $PI:~/newsletter-assistant/
```

## 3. Deploy on Pi

```bash
ssh $PI "cd ~/newsletter-assistant && \
  DOCKER_USER=local docker compose -f docker-compose.yml -f docker-compose.pi.yml up -d"
```

Access at `http://<PI_IP>:8080`

## Updating

Repeat steps 1 and 3. Images are replaced, containers recreated.

```bash
# After rebuilding & transferring new images:
ssh $PI "cd ~/newsletter-assistant && \
  DOCKER_USER=cyyang docker compose -f docker-compose.yml -f docker-compose.pi.yml up -d --force-recreate"
```
