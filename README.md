# Pulse

A modular DevOps monitoring platform deployed on AWS with a full CI/CD pipeline. Built to monitor infrastructure health, track service uptime, and measure engineering performance through DORA metrics.

**Live demo:** [https://pulse-hq.dev](https://pulse-hq.dev)

## What it does

Pulse is a single-pane-of-glass monitoring dashboard for the things engineering teams actually care about:

- **Server health** — live CPU, memory, and disk metrics from the host
- **Service uptime** — periodic reachability checks against external dependencies with latency tracking
- **DORA metrics** — deployment frequency and change failure rate computed from the GitHub API
- **Health score** — composite 0-100 score that weights all signals into a single number

All metrics refresh in real time on the frontend; no manual refresh needed.

## Architecture

\`\`\`
                       ┌──────────────────┐
                       │   Cloudflare     │  DNS + proxy + edge SSL
                       │  pulse-hq.dev    │
                       └────────┬─────────┘
                                │ HTTPS
                       ┌────────▼─────────┐
                       │   Production     │  EC2 (eu-central-1)
                       │   ┌──────────┐   │  Elastic IP — stable across rebuilds
                       │   │  nginx   │   │
                       │   │  (TLS)   │   │
                       │   └────┬─────┘   │
                       │   ┌────▼─────┐   │
                       │   │  Flask   │   │  /health /metrics /uptime /dora /score
                       │   └──────────┘   │
                       └──────────────────┘
                                ▲
                                │ ansible-playbook
                                │
   ┌──────────┐   push    ┌─────┴──────┐   pull    ┌──────────┐
   │  GitHub  │──────────▶│  GitHub    │──────────▶│   ECR    │
   │  (main)  │           │  Actions   │           │ (Docker) │
   └──────────┘           └────────────┘           └──────────┘
\`\`\`

Two environments share the same pipeline:
- **Staging** at `staging.pulse-hq.dev` — for verifying changes before promotion
- **Production** at `pulse-hq.dev` — the public site

Each environment has its own EC2 with a stable Elastic IP, a Let's Encrypt certificate (issued via DNS-01 against Cloudflare), and an Ansible-managed Docker deployment. Ansible Vault stores secrets (AWS keys, GitHub token) encrypted at rest.

## Tech stack

- **Infrastructure:** Terraform, AWS EC2, AWS ECR, Cloudflare
- **CI/CD:** GitHub Actions (build + push), Ansible (deploy)
- **Backend:** Python 3.11, Flask, psutil, GitHub API
- **Frontend:** Nginx, vanilla JS, single-page dashboard
- **TLS:** Let's Encrypt with DNS-01 challenge (Cloudflare API)
- **Secrets:** Ansible Vault (AES-256)

## Deployment pipeline

1. Push to `main` on GitHub
2. GitHub Actions builds backend and frontend Docker images and pushes them to ECR
3. Ansible playbook (run from local) pulls images from ECR onto the target EC2 and starts them with the correct env vars and mounted certs
4. Frontend nginx serves the SPA on `:443` and reverse-proxies `/api/*` to the Flask backend on `:5000`

The same playbook deploys both staging and production — the only difference is the inventory file:

\`\`\`bash
# Deploy to staging
ansible-playbook -i ansible/inventory/staging.ini ansible/deploy.yml --ask-vault-pass

# Deploy to production
ansible-playbook -i ansible/inventory/production.ini ansible/deploy.yml --ask-vault-pass
\`\`\`

## Project layout

\`\`\`
pulse/
├── portal/
│   ├── backend/         # Flask app, Dockerfile
│   └── frontend/        # nginx + dashboard, Dockerfile
├── ansible/
│   ├── deploy.yml       # main playbook
│   ├── vault.yaml       # encrypted secrets (gitignored decrypted form)
│   └── inventory/       # staging.ini, production.ini
├── terraform/
│   └── main.tf          # EC2s, security groups, Elastic IPs
├── .github/workflows/
│   └── deploy.yml       # CI: build + push to ECR
└── docs/
    └── screenshot.png
\`\`\`

## Notes

- Both EC2s use Elastic IPs with `prevent_destroy = true` so the IPs survive Terraform rebuilds
- Backend uses a fine-grained GitHub PAT to query DORA metrics (avoids the 60/hr unauthenticated rate limit)
- Cloudflare Cache Rule bypasses cache for `/api/*` to keep dashboard data fresh
- TLS certs are managed per-EC2 via certbot's DNS-01 plugin and auto-renew via systemd timer

---

Built by [Ionel Andrei Cataon](https://github.com/Bragashh/pulse).