#!/usr/bin/env bash
set -o errexit

mkdir -p media/artworks
python manage.py collectstatic --noinput
python manage.py migrate
