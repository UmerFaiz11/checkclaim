#!/usr/bin/env python3
"""
checkclaim command line tool.

    checkclaim run <name> -- <command>              run something and record the real result
    checkclaim verify "<claim text>"                 check a claim against what's recorded
    checkclaim verify --clipboard                    same, but read the claim off the clipboard
    checkclaim check <name> "<claim>" -- <command>   run something and check a claim about it, in one step
    checkclaim summary                               see what's been logged so far, in one place
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import claims
import clipboard
import ledger
import reconcile
import summary

EXIT_CODES = {"VERIFIED": 0, "CONTRADICTION": 1, "UNKNOWN": 2}


def cmd_run(args):
    entry = ledger.record_run(args.repo, args.name, args.command)
    print(f"[checkclaim] recorded '{args.name}': "
          f"command={' '.join(args.command)!r} exit_code={entry['exit_code']}")
    return 0


def _resolve_claim_text(args):
    """Shared by verify and check: figure out what claim text to check,
    either from the argument or from the clipboard. Returns (text, error)."""
    if args.clipboard:
        return clipboard.read()
    if not args.claim:
        return None, "no claim given, either pass one or use --clipboard"
    return args.claim, None


def _check_claim(repo, claim_text, freshness):
    """The actual claim-vs-evidence check, shared by verify and check.
    Prints the result and returns the exit code to use."""
    ctype, params = claims.parse_claim(claim_text)

    print("CLAIM:")
    print(claim_text)
    print()

    if ctype is None:
        print("EVIDENCE:")
        print("(no deterministic evidence source is defined for this claim)")
        print()
        print("VERDICT:")
        print("UNKNOWN")
        return EXIT_CODES["UNKNOWN"]

    if ctype == "TEST_PASSED":
        result = reconcile.check_test_passed(repo)
    elif ctype == "TEST_FAILED":
        result = reconcile.check_test_failed(repo)
    elif ctype == "BUILD_SUCCEEDED":
        result = reconcile.check_build_succeeded(repo)
    elif ctype == "BUILD_FAILED":
        result = reconcile.check_build_failed(repo)
    elif ctype == "COMMIT_CREATED":
        result = reconcile.check_commit_created(repo, freshness_seconds=freshness)
    elif ctype == "FILE_CREATED":
        result = reconcile.check_file_created(repo, params.get("filename"))
    else:
        result = {"status": "UNKNOWN", "evidence_desc": "unhandled claim type",
                   "exit_code": None, "output": None}

    print("EVIDENCE:")
    print(result["evidence_desc"])
    print()
    if result.get("exit_code") is not None:
        print("EXIT CODE:")
        print(result["exit_code"])
        print()
    if result.get("output"):
        print("OUTPUT:")
        print(result["output"])
        print()
    print("VERDICT:")
    print(result["status"])

    return EXIT_CODES[result["status"]]


def cmd_verify(args):
    claim_text, err = _resolve_claim_text(args)
    if err:
        print(f"[checkclaim] {err}")
        return EXIT_CODES["UNKNOWN"]
    return _check_claim(args.repo, claim_text, args.freshness)


def cmd_check(args):
    entry = ledger.record_run(args.repo, args.name, args.command)
    print(f"[checkclaim] recorded '{args.name}': "
          f"command={' '.join(args.command)!r} exit_code={entry['exit_code']}")
    print()

    claim_text, err = _resolve_claim_text(args)
    if err:
        print(f"[checkclaim] {err}")
        return EXIT_CODES["UNKNOWN"]
    return _check_claim(args.repo, claim_text, args.freshness)


def cmd_summary(args):
    turns = summary.load_turns(args.repo)
    log_path = os.path.join(args.repo, ".checkclaim", "verdicts.jsonl")

    if turns is None:
        print(f"No {log_path} found yet.")
        print("Either the hook isn't wired up in this project, or nothing's happened here yet.")
        return 0
    if not turns:
        print(f"{log_path} exists but is empty.")
        return 0

    print(summary.build_report(turns))
    return 0


def _split_off_command(argv):
    """Everything after the first '--' is the real command to run, taken
    completely literally. Splitting this out by hand, before argparse
    ever sees it, avoids a real argparse quirk: REMAINDER positionals
    can swallow an earlier --flag instead of leaving it for argparse to
    parse normally, when there's also an optional positional in front of
    them. Simpler to just not involve REMAINDER at all."""
    if "--" in argv:
        i = argv.index("--")
        return argv[:i], argv[i + 1:]
    return argv, []


def main():
    checkclaim_args, command = _split_off_command(sys.argv[1:])

    parser = argparse.ArgumentParser(prog="checkclaim")
    parser.add_argument("--repo", default=".", help="working directory (default: cwd)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="run a command and record its real result")
    p_run.add_argument("name", help="a label for this check, e.g. 'test' or 'build'")
    p_run.set_defaults(func=cmd_run)

    p_verify = sub.add_parser("verify", help="check a claim against recorded evidence")
    p_verify.add_argument("claim", nargs="?", help="the claim text, in quotes (omit if using --clipboard)")
    p_verify.add_argument("--clipboard", action="store_true",
                           help="read the claim text from the system clipboard instead")
    p_verify.add_argument("--freshness", type=int, default=300,
                           help="seconds within which a commit counts as recent (default 300)")
    p_verify.set_defaults(func=cmd_verify)

    p_check = sub.add_parser("check", help="run a command and check a claim about it, in one step")
    p_check.add_argument("name", help="a label for this check, e.g. 'test' or 'build'")
    p_check.add_argument("claim", nargs="?",
                          help="the claim text to check afterward, in quotes (omit if using --clipboard)")
    p_check.add_argument("--clipboard", action="store_true",
                          help="read the claim text from the system clipboard instead")
    p_check.add_argument("--freshness", type=int, default=300,
                          help="seconds within which a commit counts as recent (default 300)")
    p_check.set_defaults(func=cmd_check)

    p_summary = sub.add_parser("summary", help="show a readable summary of what's been logged")
    p_summary.set_defaults(func=cmd_summary)

    args = parser.parse_args(checkclaim_args)
    args.command = command

    if args.cmd in ("run", "check") and not args.command:
        if args.cmd == "check":
            example = 'checkclaim check test "the tests passed" -- npm test'
        else:
            example = "checkclaim run test -- npm test"
        parser.error(f"{args.cmd} needs a command after --, e.g. {example}")

    rc = args.func(args)
    sys.exit(rc)


if __name__ == "__main__":
    main()
