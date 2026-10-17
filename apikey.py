"""Where the API key lives - which is nowhere near this repository.

The key is read from, in order:

  1. the ANTHROPIC_API_KEY environment variable
  2. %APPDATA%\\GoogleDocTyper\\api_key

Both live outside the project folder, so there is no file inside the repo
that could be committed by accident. That is the whole design: not "remember
to gitignore it", but "it is not in the repo to begin with".

Nothing here ever prints or logs the key.
"""

from __future__ import annotations

import os

ENV_VAR = "ANTHROPIC_API_KEY"
APP_FOLDER = "GoogleDocTyper"
KEY_FILE = "api_key"


def key_path():
    """The off-repo file the key is kept in."""
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, APP_FOLDER, KEY_FILE)


def load_key():
    """Return the key, or None. Environment wins over the stored file."""
    from_env = os.environ.get(ENV_VAR, "").strip()
    if from_env:
        return from_env
    try:
        with open(key_path(), encoding="utf-8") as fh:
            return fh.read().strip() or None
    except OSError:
        return None


def save_key(key):
    """Store the key outside the repo, readable only by this user."""
    key = (key or "").strip()
    path = key_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(key)
    # strip inherited permissions, grant this user only
    if os.name == "nt":
        os.system(f'icacls "{path}" /inheritance:r /grant:r "%USERNAME%":F >nul 2>&1')
    else:
        os.chmod(path, 0o600)
    return path


def forget_key():
    try:
        os.remove(key_path())
        return True
    except OSError:
        return False


def describe():
    """A safe, loggable description - never the key itself."""
    if os.environ.get(ENV_VAR, "").strip():
        return f"using the {ENV_VAR} environment variable"
    key = load_key()
    if key:
        return f"using the key stored in {key_path()} (ends ...{key[-4:]})"
    return "no API key set"
