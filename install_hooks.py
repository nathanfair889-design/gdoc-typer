"""Turn on the credential-blocking pre-commit hook.

Run once per clone:   python install_hooks.py

Git does not ship hooks with a repository, so this points core.hooksPath at
the committed .githooks directory. Undo with:

    git config --unset core.hooksPath
"""

import os
import subprocess
import sys

here = os.path.dirname(os.path.abspath(__file__))
hooks = os.path.join(here, ".githooks")

if not os.path.isdir(hooks):
    sys.exit("No .githooks directory next to this script.")

try:
    subprocess.run(["git", "config", "core.hooksPath", ".githooks"],
                   cwd=here, check=True)
except (OSError, subprocess.CalledProcessError) as exc:
    sys.exit(f"Could not configure git: {exc}")

# the hook must be executable for git to run it on non-Windows checkouts
hook = os.path.join(hooks, "pre-commit")
try:
    os.chmod(hook, 0o755)
except OSError:
    pass

print("Pre-commit hook enabled.")
print("Commits containing anything shaped like an API key will be refused.")
print()
print("To test it, put a fake key in a file and try to commit it:")
# built at runtime so this source file does not itself contain key-shaped
# text - the hook would (correctly) refuse to commit it if it did
print('  echo ' + "sk-ant-" + "api03-" + "0" * 24 + " > leak.txt")
print("  git add leak.txt && git commit -m test      # should be refused")
