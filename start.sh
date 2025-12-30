#!/usr/bin/env bash
set -o errexit

# Render disk is mounted at runtime, so /var/data is writable here
mkdir -p /var/data/media/artworks
mkdir -p /var/data/sales

python manage.py migrate --noinput

exec gunicorn secondstate.wsgi:application
