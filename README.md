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

Requires Python 3 and git. No dependencies beyond the standard library. Works the same
whether you use Claude Code from the terminal, the VS Code extension, or the Desktop app,
since all three share the same engine and the same settings.

### option A: as a hook (works today, this is what's actually been tested)

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
         { "hooks": [ { "type": "command", "command": "python3 /path/to/checkclaim/stop_hook.py" } ] }
       ]
     }
   }
   ```
   Swap in the real path to where you cloned it. See `examples/settings.json`.
3. Add `.checkclaim/` to that repo's `.gitignore`.

That's it. Just use Claude Code normally. A `.checkclaim/verdicts.jsonl` file will start
filling up in that project with what actually happened at the end of each turn.

### option B: as a plugin (avoids hand-editing settings.json, not yet verified end to end)

Claude Code has a plugin system, and this repo is laid out as one (`.claude-plugin/plugin.json`
plus `hooks/hooks.json`), so you can point Claude Code at the cloned folder directly instead
of copying JSON by hand:

```bash
claude --plugin-dir /path/to/checkclaim
```

Being upfront about this one: it's built exactly to the documented plugin schema, but I
don't have the Claude Code CLI on the machine this was built on, so I haven't been able to
actually run `--plugin-dir` against it myself yet. If you try it, I'd genuinely like to know
whether it loads cleanly, that's real information option A doesn't have any way to give me.
A proper `/plugin install` flow from a public marketplace would need one more file
(`marketplace.json`) that hasn't been built yet either, so for now `--plugin-dir` is as far
as this goes.

You can also use it by hand, without the hook:

```bash
./checkclaim run test -- npm test
./checkclaim verify "the tests passed"
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
