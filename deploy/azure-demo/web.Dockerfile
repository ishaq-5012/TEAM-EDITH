FROM node:20-bookworm-slim AS build
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM caddy:2-alpine
COPY deploy/azure-demo/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /src/dist /srv/verifyflow
