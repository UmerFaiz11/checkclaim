"""
Evidence capture.

Everything in this file runs commands and reads real state (git, the
filesystem). Nothing in here ever looks at what an agent claimed to have
done. That separation is the whole point of the tool: the evidence has
to exist before we look at the claim, otherwise the claim could just
shape its own evidence.
"""

import hashlib
import json
import os
import subprocess
import time


def _ledger_dir(repo_dir):
    d = os.path.join(repo_dir, ".checkclaim")
    os.makedirs(d, exist_ok=True)
    return d


def _ledger_path(repo_dir):
    return os.path.join(_ledger_dir(repo_dir), "ledger.json")


def load_ledger(repo_dir):
    path = _ledger_path(repo_dir)
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def save_ledger(repo_dir, data):
    with open(_ledger_path(repo_dir), "w") as f:
        json.dump(data, f, indent=2)


def git_fingerprint(repo_dir):
    """
    Hash of the current working tree, used to detect staleness later.

    Two calls return the same hash as long as no tracked or untracked
    file's contents have changed in between. If they differ, something
    in the repo moved since the last check.

    This hashes actual file contents rather than `git diff HEAD`. An
    earlier version used the diff, which seemed reasonable but breaks
    the moment you commit: `git diff HEAD` goes back to empty right
    after a commit even though nothing about the files changed, so a
    normal "run tests, then commit" workflow made every prior test
    result look stale for no real reason. Hashing the files themselves
    doesn't care whether they're committed or not.

    Returns None if this isn't a usable git repo. Callers should treat
    that as "can't tell if this is stale," not "definitely not stale."
    """
    try:
        tracked = subprocess.run(
            ["git", "ls-files"],
            cwd=repo_dir, capture_output=True, text=True, timeout=10,
        )
        if tracked.returncode != 0:
            return None
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=repo_dir, capture_output=True, text=True, timeout=10,
        )

        h = hashlib.sha256()
        all_files = sorted(set(tracked.stdout.splitlines()) | set(untracked.stdout.splitlines()))
        for fname in all_files:
            # skip our own state directory, or every write would invalidate itself
            if fname == ".checkclaim" or fname.startswith(".checkclaim/"):
                continue
            path = os.path.join(repo_dir, fname)
            h.update(f"\x00file:{fname}\x00".encode())
            try:
                with open(path, "rb") as f:
                    h.update(f.read())
            except OSError as e:
                h.update(f"<<unreadable:{e}>>".encode())
        return h.hexdigest()
    except Exception:
        return None


def record_run(repo_dir, name, command):
    """
    Run `command` for real and store its exit code and output.

    This is how most evidence gets into the ledger. It's a plain
    subprocess call, nothing fancy, and it has no idea what claim (if
    any) will eventually be checked against it.
    """
    started = time.time()
    proc = subprocess.run(command, cwd=repo_dir, capture_output=True, text=True)
    entry = {
        "name": name,
        "command": command,
        "exit_code": proc.returncode,
        "stdout_tail": proc.stdout[-2000:],
        "stderr_tail": proc.stderr[-2000:],
        "output_tail": (proc.stdout + proc.stderr).strip()[-2000:],
        "started_at": started,
        "recorded_at": time.time(),
        "source": "executed",
        "fingerprint": git_fingerprint(repo_dir),
        "stale_intraturn": False,
    }
    append_entry(repo_dir, name, entry)
    return entry


def append_entry(repo_dir, name, entry):
    """
    Add a pre-built evidence entry, e.g. one reconstructed by the Stop
    hook from a Claude Code transcript instead of run directly by us.

    Entries are appended, never overwritten, so the history of what ran
    and when is always there if you want to look back at it.
    """
    ledger = load_ledger(repo_dir)
    ledger.setdefault(name, []).append(entry)
    save_ledger(repo_dir, ledger)
    return entry


def get_last_run(repo_dir, name):
    entries = load_ledger(repo_dir).get(name)
    if not entries:
        return None
    return entries[-1]
