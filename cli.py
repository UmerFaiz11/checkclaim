#!/usr/bin/env python3
"""
checkclaim command line tool.

    checkclaim run <name> -- <command>   run something and record the real result
    checkclaim verify "<claim text>"     check a claim against what's recorded
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import claims
import ledger
import reconcile

EXIT_CODES = {"VERIFIED": 0, "CONTRADICTION": 1, "UNKNOWN": 2}


def cmd_run(args):
    entry = ledger.record_run(args.repo, args.name, args.command)
    print(f"[checkclaim] recorded '{args.name}': "
          f"command={' '.join(args.command)!r} exit_code={entry['exit_code']}")
    return 0


def cmd_verify(args):
    claim_text = args.claim
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
        result = reconcile.check_test_passed(args.repo)
    elif ctype == "BUILD_SUCCEEDED":
        result = reconcile.check_build_succeeded(args.repo)
    elif ctype == "COMMIT_CREATED":
        result = reconcile.check_commit_created(args.repo, freshness_seconds=args.freshness)
    elif ctype == "FILE_CREATED":
        result = reconcile.check_file_created(args.repo, params.get("filename"))
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


def main():
    parser = argparse.ArgumentParser(prog="checkclaim")
    parser.add_argument("--repo", default=".", help="working directory (default: cwd)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="run a command and record its real result")
    p_run.add_argument("name", help="a label for this check, e.g. 'test' or 'build'")
    p_run.add_argument("command", nargs=argparse.REMAINDER, help="command to run, after --")
    p_run.set_defaults(func=cmd_run)

    p_verify = sub.add_parser("verify", help="check a claim against recorded evidence")
    p_verify.add_argument("claim", help="the claim text, in quotes")
    p_verify.add_argument("--freshness", type=int, default=300,
                           help="seconds within which a commit counts as recent (default 300)")
    p_verify.set_defaults(func=cmd_verify)

    args = parser.parse_args()

    if args.cmd == "run":
        cmd = args.command
        if cmd and cmd[0] == "--":
            cmd = cmd[1:]
        args.command = cmd
        if not args.command:
            parser.error("run needs a command after --, e.g. checkclaim run test -- npm test")

    rc = args.func(args)
    sys.exit(rc)


if __name__ == "__main__":
    main()
