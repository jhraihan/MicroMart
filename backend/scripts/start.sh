#!/bin/sh
# Container start command: bring the schema up to date, then serve.
#
# Runs on every start. Migrations and createcachetable are no-ops when there is
# nothing to do, so a restart costs a second or two. It runs here rather than
# as a platform pre-deploy step because Render's free instances have no
# pre-deploy command -- this works on every plan.
set -e

python manage.py migrate --noinput
python manage.py createcachetable

# One-time catalogue seeding, for a fresh database. Both commands are
# idempotent and never rewrite stock on an existing variant, so leaving this
# on is safe -- but it adds ~20s to every start, so turn it off once the
# catalogue is in.
if [ "${SEED_ON_START:-false}" = "true" ]; then
  # The admin password documented in the README is public. A deployment that
  # seeds with it hands the dashboard to anyone who has read the repository.
  if [ -z "${DEMO_ADMIN_PASSWORD:-}" ]; then
    echo "SEED_ON_START is on but DEMO_ADMIN_PASSWORD is empty; refusing to seed an admin with the published default." >&2
    exit 1
  fi
  python manage.py seed_demo \
    --admin-email "${DEMO_ADMIN_EMAIL:-admin@example.com}" \
    --admin-password "$DEMO_ADMIN_PASSWORD"
  python manage.py seed_catalog
fi

# Real product photography from Wikimedia. It is network-bound and takes
# minutes, so it runs beside the server rather than in front of it -- the site
# is up with generated artwork meanwhile. Already-fetched items are skipped.
if [ "${FETCH_MEDIA_ON_START:-false}" = "true" ]; then
  python manage.py fetch_media &
fi

# Render routes to $PORT and terminates TLS in front of us, so the forwarded
# headers are the platform's own. WEB_CONCURRENCY=2 fits 512 MB.
exec gunicorn config.wsgi:application \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers "${WEB_CONCURRENCY:-2}" \
  --timeout 60 \
  --forwarded-allow-ips "*" \
  --access-logfile -
