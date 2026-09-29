#!/bin/sh
# Starts as root only long enough to hand the media directory to the app user.
#
# A persistent disk mounted at /app/media arrives owned by root, and the app
# must write product images to it. Everything after the chown -- migrations,
# seeding, Gunicorn -- runs unprivileged.
set -e

if [ "$(id -u)" = "0" ]; then
  mkdir -p /app/media
  chown -R app:app /app/media
  exec env HOME=/home/app setpriv --reuid=app --regid=app --init-groups "$@"
fi

exec "$@"
