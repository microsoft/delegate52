# <img src="../assets/domain_icons/docker.svg" width="28" height="28" style="vertical-align: middle;"> Docker

**Category:** Code &amp; Configuration
**File format:** `Dockerfile`
**Summary:** Dockerfiles with multi-stage builds, services, and deployment configuration
**Work environments released:** 6 / 6

Docker domain files contain Dockerfiles with multi-stage builds, service definitions, and deployment configuration. Each Dockerfile may include multiple build stages (`FROM ... AS`), `RUN` commands for package installation and compilation, `COPY`/`ADD` instructions for file transfers, and runtime configuration (`ENV`, `EXPOSE`, `HEALTHCHECK`, `ENTRYPOINT`). This domain tests an LLM's ability to manipulate container build configurations — splitting stages across files, migrating base images, extracting runtime config, and optimizing build caching strategies.

**Domain implementation:** [`domain_docker.py`](../domains/domain_docker.py)

---

## Evaluation

The Docker domain evaluator parses Dockerfiles into structured multi-stage representations and scores reconstruction quality across six dimensions:

- **Stage structure** — Are all stages present with correct names and base images? (Count ratio, name Jaccard, base image matching)
- **Instruction sequence** — Are instructions in the correct order per stage? (SequenceMatcher on keywords)
- **RUN commands** — Are shell commands preserved accurately? (SequenceMatcher on normalized text)
- **Configuration** — Are ENV, ARG, EXPOSE, HEALTHCHECK, and ENTRYPOINT/CMD correct? (Key coverage + value accuracy)
- **COPY/ADD instructions** — Are file transfer operations preserved? (SequenceMatcher on normalized args)
- **Comment preservation** — Are inline comments intact? (SequenceMatcher on concatenated text)

**Score formula:** Weighted geometric mean of core components (stage 25%, instruction 15%, RUN 25%, config 20%, copy 15%) scaled by comments as additive modifier (90%–100%).

---

## Example Work Environment: `docker1`

**Document:** Jitsu Multi-Service Build
**Source:** [jitsucom/jitsu](https://github.com/jitsucom/jitsu/blob/newjitsu/all.Dockerfile) (MIT License)
**Size:** 202 lines · 2,082 tokens

### Seed Document Excerpt (`Dockerfile`)

```dockerfile
# Multi-stage Dockerfile for building Jitsu services (console, rotor, profiles)
#
# Usage:
#   docker buildx build --target console -t jitsucom/console:latest .
#   docker buildx build --target rotor -t jitsucom/rotor:latest .
#   docker buildx build --target profiles -t jitsucom/profiles:latest .
#
# Build with version info:
#   docker buildx build --target console \
#     --build-arg JITSU_BUILD_VERSION=1.0.0 \
#     --build-arg JITSU_BUILD_COMMIT_SHA=abc123 \
#     -t jitsucom/console:1.0.0 .

# ============================================================================
# BASE STAGE - Shared runtime image for all services
# ============================================================================
# This stage provides the minimal Node.js runtime environment
# Shared by all final service images (console, rotor, profiles)
FROM node:24-bookworm-slim AS base

WORKDIR /app

# Install runtime dependencies required by all services
# - nano, curl: debugging and healthchecks
# - cron: scheduled tasks for console
# - bash: shell scripting
# - netcat-traditional: network utilities
# - procps: process management (ps, top, etc.)
# - jq: JSON parsing for extracting package versions
RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates nano curl cron bash netcat-traditional procps jq && \
    rm -rf /var/lib/apt/lists/*

# ============================================================================
# BUILDER STAGE - Build all TypeScript/JavaScript code
# ============================================================================
# Uses jitsu-builder image which has:
# - Node.js 24, pnpm 10, build tools (g++, make, python)
# - Pre-populated pnpm store with all dependencies at /pnpm-store
# - Playwright browsers pre-installed
FROM jitsucom/jitsu-builder:latest AS builder

ARG CI=false

WORKDIR /app

# STEP 1: Copy lockfiles and workspace config (smallest possible layer)
# This layer only invalidates when dependency versions change
COPY pnpm-lock.yaml pnpm-workspace.yaml package.json ./

# STEP 2: Fetch dependencies into pnpm store
# The builder image already has most packages cached at /pnpm-store
# This step verifies the store and fetches any new/updated packages
# --ignore-scripts: Skip postinstall scripts (they run during install step)
RUN echo "pnpm store path: $(pnpm store path)" && pnpm fetch --ignore-scripts
```
<sup>Showing 55 of 202 lines. The full Dockerfile contains 4 build stages (base, builder, console, rotor) for the Jitsu analytics platform, with multi-stage COPY --from references, build ARGs, and healthchecks.</sup>

---

### Edit Tasks (6 total)

Each edit task is a reversible pair: a **forward** instruction that transforms the seed document, and a **backward** instruction that recovers the original.

| # | Edit | Forward Instruction | Backward Instruction | Operations |
|---|------|--------------------|--------------------|------------|
| 1 | **Security Hardening** | Harden the console stage: add non-root user, `--chown=runner:runner` on all COPYs, replace curl with wget in base stage, update HEALTHCHECK, add OCI metadata labels. | Remove non-root user setup and `--chown` flags from console. Switch healthcheck back to curl, restore in base apt-get. Remove OCI LABELs. | string manipulation |
| 2 | **Service Addition** | Add a Python-based `profiles` ML service stage (python:3.12-slim-bookworm, port 3402, healthcheck on /health). Alphabetize service stages and update header comments. | Remove the profiles stage entirely. Restore header comment service list to (console, rotor, profiles) for separate build. | context expansion, sorting |
| 3 | **Service Splitting** | Split into per-service Dockerfiles (Dockerfile.base, .builder, .console, .rotor) with image name references replacing stage aliases. Update usage comments per file. | Consolidate per-service Dockerfiles into a single multi-stage Dockerfile with named stages and `--target` usage header. | split & merge, format knowledge |
| 4 | **Compose Extraction** | Extract runtime config (EXPOSE, HEALTHCHECK, ENV, ENTRYPOINT) from console/rotor stages into docker-compose.yml. Keep Dockerfile build-only. | Inline the runtime configuration from docker-compose.yml back into the corresponding Dockerfile stages. Remove docker-compose.yml. | split & merge, format knowledge |
| 5 | **Alpine Migration** | Migrate base to node:24-alpine with Alpine package equivalents. Update rotor adduser for Alpine. Add separate bash install for console cron. | Switch base back to Debian bookworm-slim. Restore Debian package names, adduser flags. Remove separate bash install from console. | domain knowledge |
| 6 | **BuildKit Optimization** | Add BuildKit cache mounts for pnpm fetch/install, add `syntax` directive. Extract all inline comments to COMMENTS.md with `[C1]`–`[C30]` reference tags. | Inline comments from COMMENTS.md at tagged locations. Revert cache mounts to standard RUN, restore echo prefix. Remove syntax directive and COMMENTS.md. | string manipulation, split & merge |
