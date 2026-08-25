"""
Reconciliation: compare a claim against the evidence and decide what
actually happened.

Every check here returns one of three things: VERIFIED, CONTRADICTION,
or UNKNOWN. If evidence is missing, stale, or doesn't clearly settle the
question, the answer is UNKNOWN. It never defaults to VERIFIED just
because nothing contradicts it. Absence of evidence isn't evidence of
success.
"""

import os
import subprocess
import time

import ledger


def _from_ledger(repo_dir, name):
    entry = ledger.get_last_run(repo_dir, name)
    if entry is None:
        return {
            "status": "UNKNOWN",
            "evidence_desc": f"no recorded run named '{name}' "
            f"(run `checkclaim run {name} -- <command>` first)",
            "exit_code": None,
            "output": None,
        }

    cmd_desc = " ".join(entry["command"]) if isinstance(entry["command"], list) else str(entry["command"])

    # was there a file edit after this command ran, in the same turn?
    # if so the result doesn't tell us anything about the current code
    if entry.get("stale_intraturn"):
        return {
            "status": "UNKNOWN",
            "evidence_desc": cmd_desc,
            "exit_code": entry.get("exit_code"),
            "output": "stale: code was modified after this command ran, "
            "later in the same turn, so this result is not being reused",
        }

    # same idea but across turns/sessions: compare the working tree
    # fingerprint from when the command ran to the current one
    stored_fp = entry.get("fingerprint")
    current_fp = ledger.git_fingerprint(repo_dir)
    if stored_fp is not None and current_fp is not None and stored_fp != current_fp:
        return {
            "status": "UNKNOWN",
            "evidence_desc": cmd_desc,
            "exit_code": entry.get("exit_code"),
            "output": "stale: the code has changed since this command last ran",
        }

    verdict = "VERIFIED" if entry["exit_code"] == 0 else "CONTRADICTION"
    return {
        "status": verdict,
        "evidence_desc": cmd_desc,
        "exit_code": entry["exit_code"],
        "output": entry.get("output_tail") or None,
    }


def check_test_passed(repo_dir):
    return _from_ledger(repo_dir, "test")


def check_build_succeeded(repo_dir):
    return _from_ledger(repo_dir, "build")


def check_commit_created(repo_dir, freshness_seconds=300):
    try:
        out = subprocess.run(
            ["git", "log", "-1", "--format=%ct %H"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as e:
        return {
            "status": "UNKNOWN",
            "evidence_desc": "git log -1",
            "exit_code": None,
            "output": f"could not query git: {e}",
        }

    if out.returncode != 0 or not out.stdout.strip():
        return {
            "status": "CONTRADICTION",
            "evidence_desc": "git log -1",
            "exit_code": out.returncode,
            "output": "no commits found in repository",
        }

    ts_str, sha = out.stdout.strip().split(" ", 1)
    age = time.time() - int(ts_str)
    if age <= freshness_seconds:
        return {
            "status": "VERIFIED",
            "evidence_desc": "git log -1 --format=%ct %H",
            "exit_code": 0,
            "output": f"HEAD={sha[:12]} committed {int(age)}s ago "
            f"(within the {freshness_seconds}s freshness window)",
        }
    return {
        "status": "CONTRADICTION",
        "evidence_desc": "git log -1 --format=%ct %H",
        "exit_code": 0,
        "output": f"HEAD={sha[:12]} committed {int(age)}s ago, "
        f"older than the {freshness_seconds}s freshness window",
    }


_SEARCH_EXCLUDE_DIRS = {".git", "node_modules", ".checkclaim"}


def _resolve_within_repo(repo_dir, filename):
    """
    Resolve `filename` against repo_dir and make sure the result is
    actually inside the repo. Rejects absolute paths and `../` style
    traversal that would point somewhere else on the filesystem.

    A claim's filename comes straight from the agent's own text, so we
    treat it as untrusted input. Without this check, a claim like "the
    file /etc/passwd was created" would make us report on the real
    state of an arbitrary path on the machine, which is not something
    this tool should ever do.
    """
    repo_real = os.path.realpath(repo_dir)
    candidate = filename if os.path.isabs(filename) else os.path.join(repo_dir, filename)
    candidate_real = os.path.realpath(candidate)
    try:
        if os.path.commonpath([repo_real, candidate_real]) != repo_real:
            return None
    except ValueError:
        # happens on Windows when the paths are on different drives
        return None
    return candidate_real


def _find_by_basename(repo_dir, basename):
    """
    Fallback search for a file matching `basename` anywhere in the repo,
    used when the exact path from the claim doesn't exist. Still just a
    filesystem check bounded to the repo, nothing fuzzy about it.
    """
    matches = []
    for root, dirs, files in os.walk(repo_dir):
        dirs[:] = [d for d in dirs if d not in _SEARCH_EXCLUDE_DIRS]
        if basename in files:
            matches.append(os.path.relpath(os.path.join(root, basename), repo_dir))
    return matches


def check_file_created(repo_dir, filename):
    if not filename:
        return {
            "status": "UNKNOWN",
            "evidence_desc": "filesystem check",
            "exit_code": None,
            "output": "claim looked like a file-creation claim, but no "
            "filename could be pulled out of the text",
        }

    path = _resolve_within_repo(repo_dir, filename)
    if path is None:
        return {
            "status": "UNKNOWN",
            "evidence_desc": "filesystem check",
            "exit_code": None,
            "output": f"claim referenced a path outside the project ('{filename}'), not checking it",
        }

    if os.path.isfile(path):
        return {
            "status": "VERIFIED",
            "evidence_desc": f"os.path.isfile('{filename}')",
            "exit_code": None,
            "output": "file exists",
        }

    # the exact path from the claim doesn't exist, but the claim might
    # just be missing a directory prefix (e.g. it said "constants.js"
    # after already mentioning "src/constants.js" earlier in the same
    # message). before calling this a contradiction, check if there's
    # exactly one file with that name anywhere else in the repo.
    matches = _find_by_basename(repo_dir, os.path.basename(filename))

    if len(matches) == 1:
        return {
            "status": "VERIFIED",
            "evidence_desc": f"os.path.isfile('{filename}') was false, but found "
            f"exactly one file named '{os.path.basename(filename)}' in the repo: "
            f"'{matches[0]}'",
            "exit_code": None,
            "output": "file exists, just not at the path named in the claim",
        }
    if len(matches) > 1:
        return {
            "status": "UNKNOWN",
            "evidence_desc": f"os.path.isfile('{filename}') was false; "
            f"{len(matches)} files named '{os.path.basename(filename)}' exist in the repo",
            "exit_code": None,
            "output": "ambiguous which file the claim meant: " + ", ".join(matches),
        }
    return {
        "status": "CONTRADICTION",
        "evidence_desc": f"os.path.isfile('{filename}')",
        "exit_code": None,
        "output": "file does not exist",
    }
