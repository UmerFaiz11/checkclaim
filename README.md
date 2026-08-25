# checkclaim

[![tests](https://github.com/UmerFaiz11/checkclaim/actions/workflows/test.yml/badge.svg)](https://github.com/UmerFaiz11/checkclaim/actions/workflows/test.yml)

A small tool that checks whether your AI coding agent's claims are actually true.

If Claude Code tells you "the tests passed" at the end of a turn, checkclaim quietly
double checks that against what really happened, using real evidence, not another AI
guessing. It doesn't block anything or slow you down. It just keeps an honest log so you
stop finding out three days later that "tests passed" meant "I didn't run them."

## why this exists

Agents say things like "tests passed," "the file was created," "I committed the
changes," "the build succeeded." Sometimes that's true. Sometimes the agent is working
off stale context, or ran something that looked fine but wasn't, or just says "done"
without checking. Either way, right now the only way to know for sure is to go check it
yourself, which kind of defeats the point of using an agent to move faster.

checkclaim doesn't try to guess whether a claim is trustworthy. It looks at the actual
evidence: did the test command actually exit 0? Does the file actually exist on disk?
Is there actually a new commit? Then it tells you one of three things:

- **VERIFIED** – checked it, the claim holds up
- **CONTRADICTION** – checked it, the claim is wrong, here's the real evidence
- **UNKNOWN** – can't verify this one way or the other

The important part is the third option. If checkclaim can't confirm something, it never
guesses in the agent's favor. Missing or stale evidence stays UNKNOWN, it does not
quietly become VERIFIED. That's the whole design in one sentence.

## a real bug this caught while I was building it

Early on I had checkclaim fingerprint the working tree using `git diff HEAD`, so it
could tell if code changed after a test ran. Made sense on paper. Then I ran a normal
sequence: run tests, they pass, commit the change, report back. checkclaim came back
with a "stale" warning on a test result that was completely fine.

Turns out `git diff HEAD` goes back to empty the second you commit, since HEAD now
equals your working tree, even though not a single byte in any file actually changed. So
the fingerprint flipped on every ordinary commit and made checkclaim look broken on the
most common workflow there is: test, then commit.

Fixed it by hashing the actual file contents instead of a diff against a moving target.
Small fix, but it's the kind of thing you only find by actually running the tool for
real instead of just reasoning about it, which is a decent argument for why this project
has spent more time testing against real agent sessions than adding features.

## how it works

```
agent runs a command / does something
        |
        v
independent evidence capture   (real exit code, real git state, real filesystem check)
        |
        v
claim parsing                  (plain regex, no LLM, no guessing)
        |
        v
reconciliation                 (compare the two)
        |
        v
VERIFIED / CONTRADICTION / UNKNOWN
```

The evidence side never looks at what the agent said. The claim side never influences
what evidence gets recorded. They only meet at the reconciliation step. That separation
is deliberate, it's the only reason this is trustworthy at all.

Nothing here calls an LLM. Claim matching is regex against a short list of known
phrasings, which means it's fast, free, works offline, and is very easy to reason about,
at the cost of missing claims phrased in a way it doesn't recognize yet. When that
happens it falls back to UNKNOWN, never to a guess.

## install

Requires **Claude Code** specifically, not just any Claude subscription, since it needs
real file and terminal access to your project to set itself up. Works the same whether
you're using the terminal, the VS Code extension, or the Desktop app, since all three
share the same engine and settings. A plain claude.ai chat can't install this for you,
it doesn't have access to your local files.

### the easy way: ask Claude Code to do it

Clone or download this repo, then from inside the project you want to protect, paste
this into Claude Code:

> Install checkclaim into this project by following the steps in INSTALL.md at
> /path/to/checkclaim (use the real path to wherever you put it).

It'll read `INSTALL.md`, edit `.claude/settings.json` for you, and tell you what it
changed. This isn't a separate mechanism from the manual steps below, it's Claude Code
doing exactly those same steps for you instead of you doing them by hand.

**Important: quote the path in the hook command if it contains spaces.** This bit a real
test (see below), and it'll bite you too if you cloned this into something like
`My Projects/checkclaim`. Wrap the path in escaped quotes inside the JSON string, like the
examples below already do, don't just paste a bare path in.

### option A: by hand

1. Clone this repo somewhere permanent:
   ```bash
   git clone https://github.com/UmerFaiz11/checkclaim.git
   ```
2. In the repo you want to use it in, add a `Stop` hook to `.claude/settings.json`
   (merge with anything already there, don't overwrite other hooks):
   ```json
   {
     "hooks": {
       "Stop": [
         { "hooks": [ { "type": "command", "command": "python3 \"/path/to/checkclaim/stop_hook.py\"" } ] }
       ]
     }
   }
   ```
   Swap in the real path to where you cloned it. See `examples/settings.json`.
3. Add `.checkclaim/` to that repo's `.gitignore`.

That's it. Just use Claude Code normally. A `.checkclaim/verdicts.jsonl` file will start
filling up in that project with what actually happened at the end of each turn. It's raw
JSON though, one line per turn, not exactly pleasant to read by hand. To actually see
what's in it:

```bash
./checkclaim --repo /path/to/that/project summary
```

which prints something like:

```
turns logged: 12
active days: 3 (2026-08-23 to 2026-08-25)
claims scored: 15

verdicts:
  VERIFIED          11  (73%)
  CONTRADICTION     1  (7%)
  UNKNOWN           3  (20%)

claim types seen:
  TEST_PASSED          9
  FILE_CREATED         4
  BUILD_SUCCEEDED      2

why the UNKNOWNs happened:
  claim text not recognized:  1
  evidence was stale:         2
  no evidence recorded:       0
```

**Verified for real:** ran this against a genuinely separate, independent headless Claude
Code session (`claude -p`, not this same conversation) doing real work in a throwaway repo.
It created a file, ran `npm test` for real, and reported "tests passed". checkclaim's hook
observed the actual `npm test` call from Claude Code's own transcript, saw the real exit
code (0), and logged **VERIFIED**. A separate run where the agent claimed "tests passed"
without ever running anything test-shaped correctly logged **UNKNOWN**. Both outcomes are
sitting in this repo's commit history as raw evidence, not just a claim in this README.

### option B: as a plugin, avoids hand-editing settings.json

Claude Code has a plugin system, and this repo is laid out as one (`.claude-plugin/plugin.json`
plus `hooks/hooks.json`), so you can point Claude Code at the cloned folder directly instead
of copying JSON by hand:

```bash
claude --plugin-dir /path/to/checkclaim
```

**Also verified for real**, same method as option A above: a real, independent headless
session loaded the plugin this way, ran `npm test`, claimed "tests passed", and checkclaim
correctly logged VERIFIED. `claude plugin validate` also passes clean against this repo.

One real bug this testing found and fixed: `hooks/hooks.json` originally referenced
`${CLAUDE_PLUGIN_ROOT}/stop_hook.py` without quotes, which breaks the moment that path
contains a space (which it did, in testing). Fixed by quoting it. Worth knowing this class
of bug exists if you ever edit the hook command yourself.

A proper `/plugin install` flow from a public marketplace would still need one more file
(`marketplace.json`) that hasn't been built yet, so `--plugin-dir` is as far as the plugin
path goes for now, that part of the earlier caveat still stands.

You can also use it by hand, without the hook:

```bash
./checkclaim run test -- npm test
./checkclaim verify "the tests passed"
./checkclaim summary
```

## what it can check today

Four claim types, on purpose kept small:

- tests passed
- build succeeded
- a file was created
- a commit was made

That's it for now. Adding more should happen because something real needed it, not
because it seemed like a good idea.

## known limitations

Being upfront about these rather than finding out from a GitHub issue:

- The regex parser only recognizes positive phrasing for test claims ("tests passed"),
  not "tests failed." An honest failure report currently falls through as unrecognized,
  which is safe (becomes UNKNOWN) but incomplete.
- Some very normal phrasings still slip past the parser, like "tests still pass" or
  "everything's green." Same deal, safe but incomplete.
- The parser doesn't understand negation or quotes. A sentence that quotes and rejects a
  claim can still get matched as if it were asserting it.
- If a test/build result is invalidated because the working tree changed, that trigger
  is currently a bit too broad, any file write in the same turn counts, even ones that
  have nothing to do with the code under test.
- Nothing here stops an agent from writing a command that exits 0 without honestly
  testing anything. checkclaim trusts the exit code as real evidence, it can't tell if
  the command itself was dishonest.
- This has only been built and tested against Claude Code so far.

None of these have produced a false VERIFIED in testing so far, they all fail toward
UNKNOWN, but they're real gaps and worth knowing about before you rely on this for
anything more than an extra pair of eyes.

## how this compares to similar tools

There are other projects in this space and it would be dishonest to pretend otherwise.
The closest one I've found is `proofrun` by yebiguo, which independently ties a real
exit code to a fingerprint of the working tree and reports pass/fail/stale, the same
core idea checkclaim is built around. It's scoped to checks you explicitly declare and
run through its own CLI. checkclaim's difference is trying to parse what an agent
already says in plain language, so you don't have to remember to declare a check ahead
of time, at the cost of a narrower, regex-based understanding of what "the claim" even
was.

Other tools nearby solve adjacent but different problems: some block risky commands
before they run (prevention, not verification), some capture real screenshots for a
human to review (evidence, but no automated verdict). Worth knowing about, not the same
thing this does.

## running the tests

```bash
python3 -m unittest discover -s tests -v
```

They run against real temp git repos and real subprocesses, nothing is mocked. This is
also what runs in CI on every push, see the badge at the top for current status.

## status

This has been tested against real headless Claude Code sessions, both adversarial
scenarios designed to try to trick it, and ordinary real coding tasks. It has not
produced a false VERIFIED in either kind of testing so far. It has not yet been used by
anyone other than the person who built it. If you try it and something looks wrong,
that's genuinely useful information, please open an issue.

## license

MIT, see LICENSE.
