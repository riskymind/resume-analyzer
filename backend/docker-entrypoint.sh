#!/bin/sh
# API container entrypoint.
#
#   serve (default)  validate configuration, optionally migrate, then exec uvicorn as PID 1
#   anything else    executed as-is, e.g. `python -m app.cli migrate` or `python -m app.cli check-config`
#
# Environment (all optional):
#   PORT                       port to bind (Render injects it; default 8000)
#   WEB_CONCURRENCY            uvicorn worker processes (default 1)
#   FORWARDED_ALLOW_IPS        proxies trusted for X-Forwarded-* (default 127.0.0.1; '*' behind Render/nginx)
#   RUN_MIGRATIONS_ON_START    "true" runs `alembic upgrade head` (advisory-locked) before serving; meant for
#                              platforms without a pre-deploy step. Default false: migrate deliberately.
#   GRACEFUL_SHUTDOWN_SECONDS  time in-flight requests get after SIGTERM (default 25)
set -eu

if [ "${1:-serve}" != "serve" ]; then
    exec "$@"
fi

# Fails with a readable list of configuration problems (never their values) instead of a traceback.
python -m app.cli check-config

if [ "${RUN_MIGRATIONS_ON_START:-false}" = "true" ]; then
    python -m app.cli migrate
fi

# exec: uvicorn becomes PID 1 and receives SIGTERM directly, so shutdown is graceful.
# The application writes its own structured access log, so uvicorn's is disabled.
exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --workers "${WEB_CONCURRENCY:-1}" \
    --proxy-headers \
    --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-127.0.0.1}" \
    --timeout-keep-alive 75 \
    --timeout-graceful-shutdown "${GRACEFUL_SHUTDOWN_SECONDS:-25}" \
    --no-access-log \
    --no-server-header
