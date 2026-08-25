"""
Tests for the core checkclaim modules.

Runs against real temp git repos and real subprocesses, not mocks.
The whole point of this tool is that it looks at real state, so the
tests should too.

    python3 -m unittest discover -s tests
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import claims
import clipboard
import ledger
import reconcile
import summary


def run_git(repo_dir, *args):
    subprocess.run(["git", *args], cwd=repo_dir, capture_output=True, check=True)


def make_repo():
    repo_dir = tempfile.mkdtemp(prefix="checkclaim-test-")
    run_git(repo_dir, "init", "-q")
    run_git(repo_dir, "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q", "-m", "init", "--allow-empty")
    return repo_dir


class ClaimsTests(unittest.TestCase):
    def test_recognizes_test_passed(self):
        ctype, params = claims.parse_claim("Great news, the tests passed.")
        self.assertEqual(ctype, "TEST_PASSED")

    def test_recognizes_build_succeeded(self):
        ctype, params = claims.parse_claim("The build succeeded without issues.")
        self.assertEqual(ctype, "BUILD_SUCCEEDED")

    def test_recognizes_commit_created(self):
        ctype, params = claims.parse_claim("I committed the changes just now.")
        self.assertEqual(ctype, "COMMIT_CREATED")

    def test_recognizes_file_created_with_name(self):
        ctype, params = claims.parse_claim("The file 'notes.txt' was created.")
        self.assertEqual(ctype, "FILE_CREATED")
        self.assertEqual(params["filename"], "notes.txt")

    def test_unrecognized_text_returns_none(self):
        ctype, params = claims.parse_claim("this code is pretty clean honestly")
        self.assertIsNone(ctype)

    def test_multi_claim_finds_both(self):
        found = claims.parse_claims_multi("Tests passed and the file report.txt was created.")
        types = [f[0] for f in found]
        self.assertIn("TEST_PASSED", types)
        self.assertIn("FILE_CREATED", types)

    def test_recognizes_test_failed(self):
        ctype, params = claims.parse_claim("The tests failed.")
        self.assertEqual(ctype, "TEST_FAILED")

    def test_recognizes_test_did_not_pass(self):
        ctype, params = claims.parse_claim("The tests did not pass.")
        self.assertEqual(ctype, "TEST_FAILED")

    def test_recognizes_build_failed(self):
        ctype, params = claims.parse_claim("The build failed.")
        self.assertEqual(ctype, "BUILD_FAILED")

    def test_recognizes_build_is_broken(self):
        ctype, params = claims.parse_claim("The build is broken right now.")
        self.assertEqual(ctype, "BUILD_FAILED")

    def test_recognizes_tests_still_pass(self):
        # this exact phrasing was a documented gap: "still" between
        # "tests" and "pass" used to break the match entirely
        ctype, params = claims.parse_claim("Tests still pass after the refactor.")
        self.assertEqual(ctype, "TEST_PASSED")

    def test_recognizes_tests_are_passing(self):
        ctype, params = claims.parse_claim("The tests are passing now.")
        self.assertEqual(ctype, "TEST_PASSED")

    def test_recognizes_everythings_green_idiom(self):
        # another documented gap: a common CI idiom with zero lexical
        # overlap with "test" or "pass"
        ctype, params = claims.parse_claim("Everything's green, ready to ship.")
        self.assertEqual(ctype, "TEST_PASSED")

    def test_recognizes_build_succeeds_present_tense(self):
        ctype, params = claims.parse_claim("The build succeeds now.")
        self.assertEqual(ctype, "BUILD_SUCCEEDED")

    def test_negated_claim_is_not_matched(self):
        # this exact sentence shape was a documented gap: a quoted claim
        # inside a denial used to get matched as if it were an assertion
        ctype, params = claims.parse_claim("I'm not going to tell you the tests passed.")
        self.assertIsNone(ctype)

    def test_negated_build_claim_is_not_matched(self):
        ctype, params = claims.parse_claim("The build didn't succeed.")
        self.assertIsNone(ctype)

    def test_negation_guard_does_not_break_a_real_failure_claim(self):
        # "did not pass" contains a negation word, but it's part of the
        # claim itself (asserting failure), not a denial of some other
        # claim, so it must still match as TEST_FAILED
        ctype, params = claims.parse_claim("The tests did not pass this time.")
        self.assertEqual(ctype, "TEST_FAILED")


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.repo = make_repo()

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    def test_record_run_captures_real_exit_code(self):
        entry = ledger.record_run(self.repo, "test", ["python3", "-c", "exit(0)"])
        self.assertEqual(entry["exit_code"], 0)

        entry = ledger.record_run(self.repo, "test", ["python3", "-c", "exit(1)"])
        self.assertEqual(entry["exit_code"], 1)

    def test_fingerprint_unchanged_by_a_commit_with_no_content_change(self):
        # this is the bug that shipped in an earlier version: committing
        # with no actual file changes used to flip the fingerprint,
        # because it hashed `git diff HEAD` instead of file contents
        with open(os.path.join(self.repo, "a.txt"), "w") as f:
            f.write("hello")
        run_git(self.repo, "add", "-A")
        fp_before = ledger.git_fingerprint(self.repo)

        run_git(self.repo, "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q", "-m", "add a.txt")
        fp_after = ledger.git_fingerprint(self.repo)

        self.assertEqual(fp_before, fp_after)

    def test_fingerprint_changes_when_a_file_actually_changes(self):
        with open(os.path.join(self.repo, "a.txt"), "w") as f:
            f.write("hello")
        run_git(self.repo, "add", "-A")
        run_git(self.repo, "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q", "-m", "add a.txt")
        fp_before = ledger.git_fingerprint(self.repo)

        with open(os.path.join(self.repo, "a.txt"), "w") as f:
            f.write("changed")
        fp_after = ledger.git_fingerprint(self.repo)

        self.assertNotEqual(fp_before, fp_after)


class ReconcileTests(unittest.TestCase):
    def setUp(self):
        self.repo = make_repo()

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    def test_verified_when_command_passed(self):
        ledger.record_run(self.repo, "test", ["python3", "-c", "exit(0)"])
        result = reconcile.check_test_passed(self.repo)
        self.assertEqual(result["status"], "VERIFIED")

    def test_contradiction_when_command_failed(self):
        ledger.record_run(self.repo, "test", ["python3", "-c", "exit(1)"])
        result = reconcile.check_test_passed(self.repo)
        self.assertEqual(result["status"], "CONTRADICTION")

    def test_unknown_when_nothing_recorded(self):
        result = reconcile.check_test_passed(self.repo)
        self.assertEqual(result["status"], "UNKNOWN")

    def test_test_failed_verified_when_command_actually_failed(self):
        ledger.record_run(self.repo, "test", ["python3", "-c", "exit(1)"])
        result = reconcile.check_test_failed(self.repo)
        self.assertEqual(result["status"], "VERIFIED")

    def test_test_failed_contradiction_when_tests_actually_passed(self):
        # a dishonest or mistaken "the tests failed" when they didn't
        ledger.record_run(self.repo, "test", ["python3", "-c", "exit(0)"])
        result = reconcile.check_test_failed(self.repo)
        self.assertEqual(result["status"], "CONTRADICTION")

    def test_build_failed_verified_when_build_actually_failed(self):
        ledger.record_run(self.repo, "build", ["python3", "-c", "exit(1)"])
        result = reconcile.check_build_failed(self.repo)
        self.assertEqual(result["status"], "VERIFIED")

    def test_build_failed_contradiction_when_build_actually_succeeded(self):
        ledger.record_run(self.repo, "build", ["python3", "-c", "exit(0)"])
        result = reconcile.check_build_failed(self.repo)
        self.assertEqual(result["status"], "CONTRADICTION")

    def test_stale_after_code_changes_since_the_run(self):
        with open(os.path.join(self.repo, "app.py"), "w") as f:
            f.write("print('v1')")
        run_git(self.repo, "add", "-A")
        run_git(self.repo, "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q", "-m", "v1")

        ledger.record_run(self.repo, "test", ["python3", "-c", "exit(0)"])

        # code changes after the test ran, nothing re-verifies it
        with open(os.path.join(self.repo, "app.py"), "w") as f:
            f.write("print('v2, broken now maybe')")

        result = reconcile.check_test_passed(self.repo)
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertIn("stale", result["output"])

    def test_staleness_also_applies_to_the_failed_check(self):
        # staleness is shared logic underneath both directions, confirm
        # the failed-claim path didn't lose it in the refactor
        with open(os.path.join(self.repo, "app.py"), "w") as f:
            f.write("print('v1')")
        run_git(self.repo, "add", "-A")
        run_git(self.repo, "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q", "-m", "v1")

        ledger.record_run(self.repo, "test", ["python3", "-c", "exit(1)"])

        with open(os.path.join(self.repo, "app.py"), "w") as f:
            f.write("print('v2')")

        result = reconcile.check_test_failed(self.repo)
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertIn("stale", result["output"])

    def test_not_stale_after_a_content_free_commit(self):
        # the exact regression case for the fingerprint bug: run, then
        # commit with nothing new to commit, result should stay valid
        ledger.record_run(self.repo, "test", ["python3", "-c", "exit(0)"])
        run_git(self.repo, "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q", "-m", "checkpoint", "--allow-empty")

        result = reconcile.check_test_passed(self.repo)
        self.assertEqual(result["status"], "VERIFIED")

    def test_commit_created_verified_when_recent(self):
        with open(os.path.join(self.repo, "a.txt"), "w") as f:
            f.write("x")
        run_git(self.repo, "add", "-A")
        run_git(self.repo, "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q", "-m", "add a.txt")

        result = reconcile.check_commit_created(self.repo)
        self.assertEqual(result["status"], "VERIFIED")

    def test_file_created_verified_when_it_exists(self):
        with open(os.path.join(self.repo, "notes.txt"), "w") as f:
            f.write("x")
        result = reconcile.check_file_created(self.repo, "notes.txt")
        self.assertEqual(result["status"], "VERIFIED")

    def test_file_created_contradiction_when_it_does_not_exist(self):
        result = reconcile.check_file_created(self.repo, "ghost.txt")
        self.assertEqual(result["status"], "CONTRADICTION")

    def test_file_created_finds_it_by_bare_name_in_a_subdir(self):
        os.makedirs(os.path.join(self.repo, "src"))
        with open(os.path.join(self.repo, "src", "constants.py"), "w") as f:
            f.write("x = 1")
        # claim only names the bare filename, not the src/ prefix
        result = reconcile.check_file_created(self.repo, "constants.py")
        self.assertEqual(result["status"], "VERIFIED")

    def test_file_created_ambiguous_when_two_files_share_a_name(self):
        os.makedirs(os.path.join(self.repo, "a"))
        os.makedirs(os.path.join(self.repo, "b"))
        with open(os.path.join(self.repo, "a", "dup.txt"), "w") as f:
            f.write("x")
        with open(os.path.join(self.repo, "b", "dup.txt"), "w") as f:
            f.write("y")
        result = reconcile.check_file_created(self.repo, "dup.txt")
        self.assertEqual(result["status"], "UNKNOWN")

    def test_file_created_refuses_a_path_outside_the_repo(self):
        result = reconcile.check_file_created(self.repo, "/etc/passwd")
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertIn("outside the project", result["output"])

    def test_file_created_refuses_directory_traversal(self):
        result = reconcile.check_file_created(self.repo, "../../../../etc/passwd")
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertIn("outside the project", result["output"])


class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.repo = make_repo()

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    def test_load_turns_returns_none_when_no_log_exists(self):
        self.assertIsNone(summary.load_turns(self.repo))

    def test_load_turns_reads_real_logged_entries(self):
        log_dir = os.path.join(self.repo, ".checkclaim")
        os.makedirs(log_dir)
        with open(os.path.join(log_dir, "verdicts.jsonl"), "w") as f:
            f.write('{"ts": 1000, "results": [{"claim_type": "TEST_PASSED", "status": "VERIFIED"}]}\n')
            f.write('{"ts": 1001, "results": [{"claim_type": null, "status": "UNKNOWN"}]}\n')

        turns = summary.load_turns(self.repo)
        self.assertEqual(len(turns), 2)

    def test_build_report_counts_verdicts_correctly(self):
        turns = [
            {"ts": 1000, "results": [{"claim_type": "TEST_PASSED", "status": "VERIFIED"}]},
            {"ts": 1001, "results": [{"claim_type": "TEST_PASSED", "status": "CONTRADICTION"}]},
            {"ts": 1002, "results": [{"claim_type": None, "status": "UNKNOWN"}]},
        ]
        report = summary.build_report(turns)
        self.assertIn("VERIFIED          1", report)
        self.assertIn("CONTRADICTION     1", report)
        self.assertIn("UNKNOWN           1", report)
        self.assertIn("claim text not recognized:  1", report)


class ClipboardTests(unittest.TestCase):
    def test_read_returns_a_text_error_pair_without_crashing(self):
        # not asserting on actual clipboard contents, CI machines don't
        # have a real clipboard. just confirming this never raises and
        # always returns exactly one of (text, error) as non-None.
        text, err = clipboard.read()
        self.assertTrue((text is None) != (err is None))


if __name__ == "__main__":
    unittest.main()
