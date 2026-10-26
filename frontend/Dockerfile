# VerifyFlow web tier: the production SPA build served by nginx, which also terminates HTTPS and proxies /api.
# Build from the repository root (the nginx config lives in deploy/):
#   docker build -f frontend/Dockerfile -t verifyflow-web:<version> .
# NOT built or tested in this repository's environment (no container runtime was available); see docs/DEPLOYMENT.md.
FROM node:20.18.1-bookworm-slim AS build
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
# Type-checks, then builds static assets into /src/dist. No secrets or API keys are compiled into the bundle.
RUN npm run build

FROM nginx:1.27.3-alpine
# The image's entrypoint renders /etc/nginx/templates/*.template with envsubst (only ${VERIFYFLOW_DOMAIN} is set).
COPY deploy/nginx/verifyflow.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /src/dist /usr/share/nginx/html
EXPOSE 80 443
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD wget -q -O /dev/null --no-check-certificate https://127.0.0.1/ || exit 1
