# syntax=docker/dockerfile:1.7
#
# Resume Analyzer API image. Build context: backend/
#
#   docker build -t resume-analyzer-api backend                          # production image (target: runtime)
#   docker build --build-arg INSTALL_CJK_FONTS=true -t … backend          # + Chinese/Japanese/Korean PDF fonts
#   docker build --target fake-ai -t resume-analyzer-api:fake-ai backend  # TEST ONLY: adds the test suite and
#                                                                          # the fake AI provider; never deploy it
#
# The image contains no secrets; all configuration comes from environment variables at run time.

ARG PYTHON_IMAGE=python:3.12.16-slim-bookworm

# ---------------------------------------------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH

# ---------------------------------------------------------------------------------------------------------------
# Python dependencies, installed from the pinned requirements into a venv that the runtime stage copies.
# pip's download cache lives in a BuildKit cache mount, so it never ends up in an image layer.
FROM base AS builder
RUN python -m venv "$VIRTUAL_ENV"
COPY requirements.txt ./
RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    pip install --only-binary=:all: -r requirements.txt

# Test tooling on top (pytest, ruff, mypy, httpx…), for the fake-ai stage only. Never copied into production.
FROM builder AS builder-dev
COPY requirements-dev.txt ./
RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    pip install -r requirements-dev.txt

# ---------------------------------------------------------------------------------------------------------------
FROM base AS runtime
ARG INSTALL_CJK_FONTS=false
# WeasyPrint (PDF export) needs Pango + HarfBuzz; the fonts are the metric-compatible families the five
# templates name (see docs/export-qa.md §5). fonts-noto-cjk is opt-in (docs/milestone-8-completion-report.md).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libharfbuzz-subset0 \
        fonts-liberation fonts-crosextra-carlito fonts-crosextra-caladea fonts-dejavu-core \
        $( [ "$INSTALL_CJK_FONTS" = "true" ] && echo fonts-noto-cjk ) \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app --no-create-home --shell /usr/sbin/nologin app

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=root:root alembic.ini main.py ./
COPY --chown=root:root app ./app
COPY --chown=root:root --chmod=0755 docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

# The code is owned by root and read-only for the app user; the app writes nothing to disk in production
# (PostgreSQL holds all data, exports are streamed). /app/data is only used by the SQLite fallback.
RUN mkdir -p /app/data && chown app:app /app/data
USER app:app

# The system font cache is built above (fc-cache as root); Fontconfig's per-user cache goes to /tmp,
# the only writable place for the app user besides /app/data.
ENV PORT=8000 \
    APP_ENV=production \
    XDG_CACHE_HOME=/tmp/.cache
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os,urllib.request;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/api/v1/health',timeout=4)" || exit 1

STOPSIGNAL SIGTERM
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["serve"]

# ---------------------------------------------------------------------------------------------------------------
# TEST ONLY. The production image plus the test suite, the dev tools and scripts/mock_ai_server.py (fake AI
# provider). Used by compose.fake-ai.yaml and CI to exercise the real container without AI credentials.
# mock_ai_server refuses to start with APP_ENV=production, so the default is switched to development.
FROM runtime AS fake-ai
USER root
COPY --from=builder-dev /opt/venv /opt/venv
COPY --chown=root:root pyproject.toml ./
COPY --chown=root:root tests ./tests
COPY --chown=root:root scripts ./scripts
USER app:app
ENV APP_ENV=development
CMD ["python", "-m", "scripts.mock_ai_server", "--host", "0.0.0.0", "--port", "8000"]

# The last stage is what a plain `docker build` (and Render) produces: the production image.
FROM runtime AS production
