#!/usr/bin/env python3
"""
Claude Code Stop hook entrypoint.

Claude Code fires a "Stop" event at the end of every turn, and hands the
hook a JSON payload on stdin that includes the path to that turn's own
transcript file. This hook reads that transcript to reconstruct which
Bash commands actually ran and what their real exit codes were, then
checks whatever the agent claimed in its final message against that.

The transcript comes from Claude Code's own tool-execution logging, not
from the agent's reply, so it still counts as independent evidence even
though nothing here executes a command itself.

This hook never blocks. It always lets the turn finish and just appends
a line to .checkclaim/verdicts.jsonl with what it found. Turning a
CONTRADICTION into an actual warning or a blocked turn is a reasonable
next step, just not this one.
"""

import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import claims
import ledger
import reconcile

TEST_CMD_RE = re.compile(
    r"\b(npm test|npm run test|pytest|py\.test|go test|cargo test|"
    r"jest|vitest|mocha|rspec|phpunit|dotnet test)\b", re.I
)
BUILD_CMD_RE = re.compile(
    r"\b(npm run build|make(?!file)|go build|cargo build|tsc\b|webpack|"
    r"mvn (package|install|build)|gradle build|dotnet build)\b", re.I
)
FILE_WRITE_TOOLS = {"Write", "Edit", "NotebookEdit", "MultiEdit"}
FILE_WRITE_BASH_RE = re.compile(r"(>{1,2}\s*\S|\bsed\s+-i|\bmv\s|\brm\s|\bgit\s+apply\b|\bpatch\s)")


def classify_command(cmd_text):
    if TEST_CMD_RE.search(cmd_text):
        return "test"
    if BUILD_CMD_RE.search(cmd_text):
        return "build"
    return None


PIPE_MASKS_EXIT_CODE_RE = re.compile(r"\|\s*(tail|head|grep|sed|awk|wc|less|more|sort|uniq)\b")
FAILURE_MARKER_RE = re.compile(r"\bFAILED\b|\bFAIL\b|\d+\s+failing\b|AssertionError|Traceback", re.I)


def parse_exit_code(tool_result_content, is_error):
    if not is_error:
        return 0
    if isinstance(tool_result_content, str):
        m = re.search(r"[Ee]xit code (\d+)", tool_result_content)
        if m:
            return int(m.group(1))
    return 1


def exit_code_is_reliable(cmd_text, exit_code, output_text):
    """
    A command piped into tail/head/grep/etc reports the exit code of the
    last stage in the pipe, not the command you actually care about.
    `npm test 2>&1 | tail -100` will "succeed" even when the tests fail,
    because tail itself exits 0. When we see that shape and the reported
    exit code is 0, fall back to scanning the output text for obvious
    failure markers instead of trusting the exit code as-is.
    """
    if not PIPE_MASKS_EXIT_CODE_RE.search(cmd_text):
        return True, exit_code
    if exit_code == 0 and isinstance(output_text, str) and FAILURE_MARKER_RE.search(output_text):
        return False, 1
    return True, exit_code


def reconstruct_turn(transcript_path, prompt_id):
    """Walk the transcript once, return (test_build_events, file_edit_ts)."""
    tool_uses = {}
    test_build_events = []
    file_edit_ts = []

    if not transcript_path or not os.path.exists(transcript_path):
        return test_build_events, file_edit_ts

    with open(transcript_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            msg = d.get("message", {})
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for c in content:
                kind = c.get("type")
                if kind == "tool_use":
                    tool_uses[c.get("id")] = (c.get("name"), c.get("input") or {}, d.get("timestamp"))
                elif kind == "tool_result":
                    pid = d.get("promptId")
                    if prompt_id and pid and pid != prompt_id:
                        continue
                    info = tool_uses.get(c.get("tool_use_id"))
                    if not info:
                        continue
                    name, tinput, use_ts = info
                    ts = d.get("timestamp") or use_ts
                    if name == "Bash":
                        cmd = tinput.get("command", "")
                        ctype = classify_command(cmd)
                        if ctype:
                            is_error = bool(c.get("is_error"))
                            output_text = str(c.get("content"))[:2000]
                            exit_code = parse_exit_code(c.get("content"), is_error)
                            reliable, exit_code = exit_code_is_reliable(cmd, exit_code, output_text)
                            entry = {
                                "type": ctype,
                                "command": cmd,
                                "exit_code": exit_code,
                                "output": output_text,
                                "ts": ts,
                            }
                            if not reliable:
                                entry["output"] = (
                                    "[checkclaim: exit code looked masked by a shell pipe, "
                                    "reclassified as failing based on output content] " + output_text
                                )
                            test_build_events.append(entry)
                        if FILE_WRITE_BASH_RE.search(cmd):
                            file_edit_ts.append(ts)
                    elif name in FILE_WRITE_TOOLS:
                        file_edit_ts.append(ts)

    return test_build_events, file_edit_ts


def main():
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except Exception:
        sys.exit(0)

    repo_dir = payload.get("cwd") or "."
    transcript_path = payload.get("transcript_path")
    prompt_id = payload.get("prompt_id")
    claim_text = payload.get("last_assistant_message") or ""

    test_build_events, file_edit_ts = reconstruct_turn(transcript_path, prompt_id)

    fp_now = ledger.git_fingerprint(repo_dir)
    for ev in test_build_events:
        stale_intraturn = any(t and ev["ts"] and t > ev["ts"] for t in file_edit_ts)
        entry = {
            "name": ev["type"],
            "command": ["<observed-by-stop-hook>", ev["command"]],
            "exit_code": ev["exit_code"],
            "output_tail": ev["output"],
            "recorded_at": time.time(),
            "source": "observed_stop_hook",
            "fingerprint": fp_now,
            "stale_intraturn": stale_intraturn,
        }
        ledger.append_entry(repo_dir, ev["type"], entry)

    claim_list = claims.parse_claims_multi(claim_text)
    results = []
    if not claim_list:
        results.append({
            "claim_snippet": claim_text, "claim_type": None, "status": "UNKNOWN",
            "evidence_desc": "no deterministic evidence source is defined for this claim",
            "exit_code": None, "output": None,
        })
    else:
        for ctype, params, snippet in claim_list:
            if ctype == "TEST_PASSED":
                r = reconcile.check_test_passed(repo_dir)
            elif ctype == "BUILD_SUCCEEDED":
                r = reconcile.check_build_succeeded(repo_dir)
            elif ctype == "COMMIT_CREATED":
                r = reconcile.check_commit_created(repo_dir)
            elif ctype == "FILE_CREATED":
                r = reconcile.check_file_created(repo_dir, params.get("filename"))
            else:
                r = {"status": "UNKNOWN", "evidence_desc": "unhandled claim type",
                     "exit_code": None, "output": None}
            results.append({"claim_snippet": snippet, "claim_type": ctype, **r})

    log_path = os.path.join(repo_dir, ".checkclaim", "verdicts.jsonl")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "a") as f:
        f.write(json.dumps({
            "ts": time.time(),
            "prompt_id": prompt_id,
            "final_message": claim_text,
            "observed_test_build_events": test_build_events,
            "results": results,
        }) + "\n")

    sys.exit(0)


if __name__ == "__main__":
    main()
