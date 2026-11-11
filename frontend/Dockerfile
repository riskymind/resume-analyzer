# syntax=docker/dockerfile:1.7
#
# Resume Analyzer web image. Build context: frontend/
#
#   docker build -t resume-analyzer-web frontend               # production: static build served by nginx
#   docker build --target dev -t resume-analyzer-web:dev frontend   # Vite dev server (compose.dev.yaml)
#
# The bundle contains no backend URL and no secrets: the browser calls the relative path /api, which nginx
# (here), Vite (development) or Vercel (production) forwards to the API. Only VITE_* variables can reach the
# bundle, and none are set at build time.

ARG NODE_IMAGE=node:24.22.2-alpine
ARG NGINX_IMAGE=nginxinc/nginx-unprivileged:1.28.2-alpine

# ---------------------------------------------------------------------------------------------------------------
FROM ${NODE_IMAGE} AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm,sharing=locked npm ci --no-audit --no-fund

# ---------------------------------------------------------------------------------------------------------------
# Development server with hot reload; compose.dev.yaml bind-mounts the source over /app.
FROM deps AS dev
COPY . .
EXPOSE 5173
CMD ["npx", "vite", "--host", "0.0.0.0", "--port", "5173", "--strictPort"]

# ---------------------------------------------------------------------------------------------------------------
FROM deps AS build
COPY . .
RUN npm run build

# ---------------------------------------------------------------------------------------------------------------
# Runtime: static files only (no Node, no node_modules), served by an unprivileged nginx (uid 101, port 8080).
FROM ${NGINX_IMAGE} AS runtime
# Upstream for /api; the default matches the Compose service name.
ENV API_UPSTREAM=http://api:8000
COPY --chown=root:root nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --chown=root:root nginx/security-headers.conf /etc/nginx/snippets/security-headers.conf
COPY --chown=root:root --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
