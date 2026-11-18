"""Local-only integration settings. Never include these files in exports."""
import json
import os
from contextlib import contextmanager
from pathlib import Path
from django.conf import settings


def private_dir():
    path = Path(settings.BASE_DIR) / '.private'
    path.mkdir(mode=0o700, exist_ok=True)
    return path


def read_private(name):
    try:
        return json.loads((private_dir() / name).read_text())
    except FileNotFoundError:
        return {}


def write_private(name, data):
    path = private_dir() / name
    temp = path.with_suffix('.tmp')
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as handle:
        json.dump(data, handle)
    os.replace(temp, path)


@contextmanager
def signer_lock():
    import fcntl
    with (private_dir() / 'signer.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def elevenlabs_settings():
    saved = read_private('elevenlabs.json')
    return {
        'api_key': os.environ.get('ELEVENLABS_API_KEY') or saved.get('api_key', ''),
        'voice_id': os.environ.get('ELEVENLABS_VOICE_ID') or saved.get('voice_id', 'JBFqnCBsd6RMkjVDRZzb'),
    }
