Pulse — Internal Developer Portal
A production-style internal developer portal that automates deployments across multiple environments, with a live dashboard for service health monitoring.
What It Does
Pulse is a full DevOps platform built from scratch. You push code to Gitea, Jenkins automatically picks it up, builds a Docker image, deploys it to staging, waits for manual approval, then deploys to production. A web dashboard shows the health status of all running services in real time.

Full Deployment Flow
1. Push code to Gitea
2. Jenkins detects the change automatically (Poll SCM)
3. Jenkins pulls the code and verifies project structure
4. Jenkins builds a Docker image of the service
5. Ansible copies and deploys the image to the staging EC2
6. Manual approval gate — you review staging before promoting
7. Ansible deploys the same image to the production EC2
8. Portal dashboard updates to show both services healthy
Tech Stack
ToolRoleTerraformProvisions AWS infrastructure (EC2s, security groups, SSH keys)AWS EC2Hosts staging and production environments (eu-central-1)GiteaSelf-hosted Git server — source of truth for all codeJenkinsCI/CD server — builds, tests, and deploys automaticallyDockerEvery service runs as a containerAnsibleDeploys containers to EC2s via SSHAnsible VaultEncrypts all secrets — never stored in plain textFlaskBackend API with health check endpointNginxServes the frontend portalHTML/JSPortal dashboard with live health status cards

Project Structure

pulse/
├── terraform/          ← AWS infrastructure as code
├── ansible/
│   ├── inventory/      ← staging and production IP addresses
│   │   └── group_vars/ ← environment-specific variables
│   ├── deploy.yml      ← Ansible playbook for deployments
│   ├── ansible.cfg     ← Ansible configuration
│   └── vault.yml       ← encrypted secrets (Ansible Vault)
├── jenkins/
│   └── Jenkinsfile     ← pipeline definition
├── portal/
│   ├── backend/        ← Flask API (app.py, Dockerfile)
│   └── frontend/       ← Nginx portal (index.html, Dockerfile)
└── services/           ← future service configs

Infrastructure
Two EC2 instances provisioned by Terraform on AWS (t3.micro, free tier):

Security group allows ports 22 (SSH), 80 (API), 8080 (Portal).
Pipeline Stages
Checkout → Test → Build → Deploy to Staging → Approve → Deploy to Production

Checkout — pulls latest code from Gitea
Test — verifies all required files exist
Build — builds Docker images for backend and frontend
Deploy to Staging — Ansible deploys to staging EC2
Approve Production — manual gate, requires human confirmation
Deploy to Production — Ansible deploys to production EC2

Security

All secrets encrypted with Ansible Vault (AES256)
Vault password stored locally, never committed to Git
SSH key authentication for all EC2 connections
.vault_pass excluded via .gitignore

Extensibility
Adding a new service is straightforward:

Add its IP to the Ansible inventory
Add a new card to the portal frontend
Push to Gitea — Jenkins handles the rest

Planned extensions: crypto market monitor, stock prices, weather alerts, uptime checker, energy prices.
