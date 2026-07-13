#!/usr/bin/env bash
set -o errexit
# Render disk is mounted at runtime, so /var/data is writable here
mkdir -p /var/data/media/artworks
python manage.py migrate --noinput
exec gunicorn \
  --timeout "${GUNICORN_TIMEOUT:-90}" \
  --graceful-timeout "${GUNICORN_GRACEFUL_TIMEOUT:-30}" \
  secondstate.wsgi:application
