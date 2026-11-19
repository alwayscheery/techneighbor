#!/usr/bin/env bash
set -euo pipefail
python manage.py migrate --noinput
python manage.py createcachetable
python manage.py setup_hosted
exec gunicorn techneighbor.wsgi:application --bind "0.0.0.0:${PORT:-10000}" --workers 1 --threads 1 --timeout 90 --access-logfile -
