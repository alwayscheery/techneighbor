#!/bin/zsh
set -eu
cd -- "${0:A:h}"
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py setup_demo
.venv/bin/python manage.py setup_community
.venv/bin/python manage.py setup_neighbors
echo ""
echo "Open http://127.0.0.1:8000 in your browser."
echo "Coordinator sign-in details are in LOCAL_ACCESS.txt."
echo "Keep this window open. Press Control+C to stop."
exec .venv/bin/python manage.py runserver 127.0.0.1:8000
