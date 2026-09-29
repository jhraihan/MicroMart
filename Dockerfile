# syntax=docker/dockerfile:1
#
# One image serving both the API and the React storefront from one origin --
# see "The storefront, served by this process" in config/settings/prod.py for
# why that matters to the refresh cookie.
#
#   docker build -t micromart .
#   docker run -p 8000:8000 --env-file backend/.env.production micromart

# ---- 1. The storefront -------------------------------------------------------
FROM node:22-bookworm-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
# Vite inlines VITE_* at build time, so these are build arguments, not
# runtime environment. See docs/DEPLOY-RENDER.md.
ARG VITE_SHOW_DEMO_CREDENTIALS=false
ARG VITE_SHOW_DEMO_ADMIN=false
ENV VITE_SHOW_DEMO_CREDENTIALS=$VITE_SHOW_DEMO_CREDENTIALS \
    VITE_SHOW_DEMO_ADMIN=$VITE_SHOW_DEMO_ADMIN
RUN npm run build

# ---- 2. Python wheels --------------------------------------------------------
# mysqlclient compiles against the MySQL client headers. Building wheels here
# keeps the compiler and headers out of the image that ships.
FROM python:3.12-slim-bookworm AS wheels
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential pkg-config default-libmysqlclient-dev \
 && rm -rf /var/lib/apt/lists/*
COPY backend/requirements/ /requirements/
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r /requirements/prod.txt

# ---- 3. Runtime --------------------------------------------------------------
FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=config.settings.prod \
    FRONTEND_DIST_DIR=/app/frontend_dist \
    PORT=8000

# libmariadb3 is the client library mysqlclient links against, including the
# caching_sha2_password plugin MySQL 8 uses by default.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libmariadb3 \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 1000 app

COPY --from=wheels /wheels /wheels
COPY backend/requirements/ /tmp/requirements/
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r /tmp/requirements/prod.txt \
 && rm -rf /wheels /tmp/requirements

WORKDIR /app
COPY backend/ /app/
COPY --from=frontend /frontend/dist /app/frontend_dist

# Scripts may have been checked out with CRLF endings on Windows.
RUN sed -i 's/\r$//' /app/scripts/*.sh && chmod +x /app/scripts/*.sh

# collectstatic imports settings, which insist on these. None of them is used:
# collecting static files touches neither the database nor the secret key.
RUN DJANGO_SECRET_KEY=collectstatic-only \
    DATABASE_URL=mysql://build:build@127.0.0.1:3306/build \
    DJANGO_ALLOWED_HOSTS=build.invalid \
    python manage.py collectstatic --noinput \
 && mkdir -p /app/media \
 && chown -R app:app /app/media /app/staticfiles

EXPOSE 8000
ENTRYPOINT ["/app/scripts/docker-entrypoint.sh"]
CMD ["/app/scripts/start.sh"]
