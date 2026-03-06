# Required env vars: DOCKER_USER, SERVER_IP, ACME_EMAIL
# Optional: KUBECONFIG (defaults to ~/.kube/newsletter-k3s.yaml)

KUBECONFIG ?= ~/.kube/newsletter-k3s.yaml
KH := kubectl --kubeconfig $(KUBECONFIG)

# --- Local dev (native arch) ---

.PHONY: build up down logs

build:  ## Build images for local dev (native arch)
	docker compose build

up:  ## Start all services locally
	docker compose up -d

down:  ## Stop all services
	docker compose down

logs:  ## Tail logs for all services
	docker compose logs -f

# --- Production (amd64 for Hetzner) ---

.PHONY: prod-build prod-push prod-deploy prod-all

prod-build:  ## Build images for production (linux/amd64)
	PLATFORM=linux/amd64 docker compose build

prod-push:  ## Push images to Docker Hub
	docker compose push

prod-deploy:  ## Deploy to k3s cluster
	$(KH) kustomize --load-restrictor LoadRestrictionsNone k8s/ \
	  | sed "s|docker.io/OWNER|docker.io/$(DOCKER_USER)|g" \
	  | sed "s|SERVER_IP|$(SERVER_IP)|g" \
	  | sed "s|ACME_EMAIL|$(ACME_EMAIL)|g" \
	  | $(KH) apply -f -

prod-all: prod-build prod-push prod-deploy  ## Build, push, and deploy

prod-restart:  ## Restart deployments to pull latest images
	$(KH) rollout restart deploy/newsletter-agent deploy/newsletter-frontend -n newsletter

# --- Cluster operations ---

.PHONY: pods pod-logs scale-down scale-up pipeline

pods:  ## List pods in newsletter namespace
	$(KH) get pods -n newsletter

pod-logs:  ## Tail logs for a deployment (usage: make pod-logs D=newsletter-agent)
	$(KH) logs -n newsletter deploy/$(D) -f

scale-down:  ## Scale agent to 0
	$(KH) scale deploy/newsletter-agent --replicas=0 -n newsletter

scale-up:  ## Scale agent to 1
	$(KH) scale deploy/newsletter-agent --replicas=1 -n newsletter

pipeline:  ## Run pipeline locally
	docker compose --profile pipeline run --rm pipeline

# --- Helpers ---

.PHONY: help

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*## "}; {printf "\033[36m%-16s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
