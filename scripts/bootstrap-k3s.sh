#!/usr/bin/env bash
# bootstrap-k3s.sh — Secure an Ubuntu server and install k3s (single node)
#
# Usage:
#   sudo bash bootstrap-k3s.sh <username> <ssh-public-key>
#
# Example:
#   sudo bash bootstrap-k3s.sh deploy "ssh-ed25519 AAAA... user@host"
#
# What this script does:
#   1. Creates a non-root sudo user with SSH key auth
#   2. Hardens SSH (disables root login + password auth)
#   3. Configures UFW firewall (SSH + k3s API only)
#   4. Installs fail2ban
#   5. Installs k3s (single node) and configures kubectl

set -euo pipefail

# ── Args ──────────────────────────────────────────────────────────────────────

if [[ $# -lt 2 ]]; then
  echo "Usage: sudo bash $0 <username> <ssh-public-key>"
  exit 1
fi

if [[ $EUID -ne 0 ]]; then
  echo "Error: this script must be run as root (sudo)."
  exit 1
fi

NEW_USER="$1"
SSH_PUBKEY="$2"

echo "==> Bootstrapping server: user=${NEW_USER}"

# ── 1. System update ──────────────────────────────────────────────────────────

echo "==> Updating system packages..."
apt-get update -q
apt-get upgrade -y -q
apt-get install -y -q curl ufw fail2ban

# ── 2. Create non-root sudo user ──────────────────────────────────────────────

echo "==> Creating user: ${NEW_USER}"
if id "${NEW_USER}" &>/dev/null; then
  echo "    User ${NEW_USER} already exists, skipping creation."
else
  useradd -m -s /bin/bash "${NEW_USER}"
  usermod -aG sudo "${NEW_USER}"
  echo "    Added ${NEW_USER} to sudo group."
fi

# Install SSH public key
SSH_DIR="/home/${NEW_USER}/.ssh"
mkdir -p "${SSH_DIR}"
echo "${SSH_PUBKEY}" >> "${SSH_DIR}/authorized_keys"
sort -u "${SSH_DIR}/authorized_keys" -o "${SSH_DIR}/authorized_keys"  # dedupe
chmod 700 "${SSH_DIR}"
chmod 600 "${SSH_DIR}/authorized_keys"
chown -R "${NEW_USER}:${NEW_USER}" "${SSH_DIR}"
echo "    SSH public key installed."

# ── 3. Harden SSH ─────────────────────────────────────────────────────────────

echo "==> Hardening SSH..."
SSHD_CONFIG="/etc/ssh/sshd_config"

# Back up original config once
if [[ ! -f "${SSHD_CONFIG}.bak" ]]; then
  cp "${SSHD_CONFIG}" "${SSHD_CONFIG}.bak"
fi

# Apply settings — update existing lines or append if missing
apply_sshd_setting() {
  local key="$1"
  local value="$2"
  if grep -qE "^#?${key}" "${SSHD_CONFIG}"; then
    sed -i "s|^#\?${key}.*|${key} ${value}|" "${SSHD_CONFIG}"
  else
    echo "${key} ${value}" >> "${SSHD_CONFIG}"
  fi
}

apply_sshd_setting "PermitRootLogin"          "no"
apply_sshd_setting "PasswordAuthentication"   "no"
apply_sshd_setting "PubkeyAuthentication"     "yes"
apply_sshd_setting "AuthorizedKeysFile"       ".ssh/authorized_keys"
apply_sshd_setting "X11Forwarding"            "no"
apply_sshd_setting "AllowAgentForwarding"     "no"
apply_sshd_setting "MaxAuthTries"             "3"
apply_sshd_setting "LoginGraceTime"           "30"

# Validate config before restarting
sshd -t
systemctl restart ssh
echo "    SSH hardened and restarted."

# ── 4. UFW firewall ───────────────────────────────────────────────────────────

echo "==> Configuring UFW..."
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp    comment "SSH"
ufw allow 6443/tcp  comment "k3s API server"
# Allow inter-node communication (flannel VXLAN + metrics)
ufw allow 8472/udp  comment "k3s flannel VXLAN"
ufw allow 10250/tcp comment "k3s kubelet metrics"
ufw --force enable
ufw status verbose
echo "    UFW configured."

# ── 5. fail2ban ───────────────────────────────────────────────────────────────

echo "==> Configuring fail2ban..."
cat > /etc/fail2ban/jail.local <<'EOF'
[DEFAULT]
bantime  = 1h
findtime = 10m
maxretry = 5

[sshd]
enabled  = true
port     = ssh
logpath  = %(sshd_log)s
backend  = %(sshd_backend)s
EOF

systemctl enable fail2ban
systemctl restart fail2ban
echo "    fail2ban configured (max 5 retries / 10 min, 1h ban)."

# ── 6. Install k3s ───────────────────────────────────────────────────────────

echo "==> Installing k3s (single node)..."
curl -sfL https://get.k3s.io | sh -s - \
  --write-kubeconfig-mode 644

# Wait for node to be ready
echo "    Waiting for k3s node to be ready..."
until kubectl get node &>/dev/null; do
  sleep 2
done
kubectl wait node --all --for condition=ready --timeout=120s
echo "    k3s is ready."

# ── 7. Configure kubectl for the new user ────────────────────────────────────

echo "==> Configuring kubectl for ${NEW_USER}..."
USER_HOME="/home/${NEW_USER}"
KUBE_DIR="${USER_HOME}/.kube"
mkdir -p "${KUBE_DIR}"
cp /etc/rancher/k3s/k3s.yaml "${KUBE_DIR}/config"
chown -R "${NEW_USER}:${NEW_USER}" "${KUBE_DIR}"
chmod 600 "${KUBE_DIR}/config"
echo "    kubeconfig written to ${KUBE_DIR}/config"

# ── Done ──────────────────────────────────────────────────────────────────────

echo ""
echo "========================================="
echo " Bootstrap complete!"
echo "========================================="
echo ""
echo " User:       ${NEW_USER}"
echo " SSH:        root login disabled, password auth disabled"
echo " Firewall:   UFW active (22, 6443, 8472, 10250)"
echo " fail2ban:   active"
echo " k3s:        $(k3s --version | head -1)"
echo ""
echo " Next: log in as ${NEW_USER} and verify:"
echo "   kubectl get nodes"
echo ""
echo " IMPORTANT: verify SSH access as ${NEW_USER} before closing this session."
