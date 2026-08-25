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

Two ways to use checkclaim, pick the one that matches what you actually have:

- **Free Claude** (the web chat at claude.ai, or the Claude app, no paid Claude Code
  access): a manual command you run yourself, a few extra steps, but works for anyone.
- **Claude Code** (CLI, VS Code extension, or the desktop app, on Pro/Max/Team/Enterprise):
  Claude Code sets everything up for you, and then it runs automatically forever after.

Both need the same three things installed first.

### what you need installed first

**1. Python 3**, from [python.org/downloads](https://www.python.org/downloads/). On
Windows, tick **"Add python.exe to PATH"** on the installer's first screen, it's easy to
miss and causes confusing errors later if you skip it. Check it worked by opening a
terminal (see below) and typing `python3 --version`, you should see a version number.

**2. Git**, from [git-scm.com/downloads](https://git-scm.com/downloads) on Windows, or
just type `git --version` in a terminal on a Mac and it'll offer to install itself if
it's missing. Check it worked with `git --version`.

**3. VS Code**, from [code.visualstudio.com](https://code.visualstudio.com), install it
like any other app. To open a terminal inside it: click **Terminal** in the top menu,
then **New Terminal**. A panel opens at the bottom, that's where you type the commands
below.

If you're going the Claude Code route, also install the **Claude Code** extension: click
the Extensions icon on VS Code's left sidebar (four small squares), search "Claude Code",
click Install.

### free Claude (web chat or the Claude app)

1. Create a folder for your project, or use one you already have. Open it in VS Code
   (**File → Open Folder...**), then open a terminal in it.
2. Install checkclaim as a real command, once:
   ```bash
   pipx install git+https://github.com/UmerFaiz11/checkclaim.git
   ```
3. From now on, whenever Claude gives you code and says something like "the tests
   should pass now": paste the code into your project yourself like you already do, then
   check the claim for real:
   ```bash
   checkclaim check test "the tests should pass now" -- npm test
   ```
   Or, to avoid retyping the claim since you probably just copied it anyway:
   ```bash
   checkclaim check test --clipboard -- npm test
   ```
4. It prints **VERIFIED**, **CONTRADICTION**, or **UNKNOWN** right there in the terminal,
   immediately, based on what `npm test` (or whatever your real command is) actually did.

This is a manual habit, not automatic, since a plain chat has no way to reach your files
on its own, that's a real platform limit, not something checkclaim can code around. Tested
for real: installed into a clean environment straight from this GitHub repo, and it worked
immediately, no setup beyond that one install command.

### Claude Code (CLI, VS Code extension, or desktop app)

Simpler, because Claude Code does the setup for you.

1. Open a terminal, download checkclaim once:
   ```bash
   git clone https://github.com/UmerFaiz11/checkclaim.git
   ```
2. Open your actual project in VS Code (the one you want to protect, not the checkclaim
   folder), open Claude Code there, and paste in:
   > Install checkclaim into this project by following the steps in INSTALL.md at
   > /path/to/checkclaim (use the real path from step 1)
3. That's it. Claude Code edits a config file for you and tells you what it changed. From
   here on, just use Claude Code normally, checkclaim runs quietly in the background.
4. Whenever you want to see what it's caught, swap in your real path from step 1:
   ```bash
   python3 "/path/to/checkclaim/cli.py" --repo /path/to/your/project summary
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
   ```

**Verified for real**, not just written: a genuinely separate, independent headless
Claude Code session (not this conversation) did real work in a throwaway repo, ran `npm
test` for real, and reported "tests passed". checkclaim observed the actual command from
Claude Code's own transcript, saw the real exit code, and correctly logged VERIFIED. A
separate run where the agent claimed "tests passed" without running anything correctly
logged UNKNOWN instead.

If you'd rather skip the terminal entirely and edit the config by hand, or use Claude
Code's plugin system instead (`claude --plugin-dir`), both are documented in `INSTALL.md`
and `examples/settings.json` in this repo.

## what it can check today

Four claim types, on purpose kept small:

- tests passed
- build succeeded
- a file was created
- a commit was made

That's it for now. Adding more should happen because something real needed it, not
because it seemed like a good idea.

## known limitations

Being upfront about these rather than finding out from a GitHub issue. A few of these
used to be worse and got fixed, noted below, the rest are still open on purpose.

- **Fixed:** the parser used to only recognize positive test phrasing ("tests passed"),
  so an honest "tests failed" report fell through as unrecognized. It now recognizes
  failure claims too ("tests failed," "the build failed," "the build is broken") as
  their own claim types, checked against the same real evidence, just inverted: a
  "tests failed" claim is VERIFIED when the recorded exit code is actually non-zero, and
  CONTRADICTION if the tests actually passed.
- **Fixed, for the cases actually found:** phrasings like "tests still pass," "tests are
  passing," "the build succeeds," and the "everything's green" idiom used to slip past
  the parser entirely. They're recognized now. This is still a fixed list of patterns,
  not real language understanding, some phrasing will still get past it, that's not
  something a regex-based parser is ever going to fully solve.
- **Better, not solved:** the parser now checks a short window of text right before a
  match for common negation words ("not," "didn't," "never," and similar) and skips the
  match if one's there. That catches the concrete case that used to break this, "I'm not
  going to tell you the tests passed," but it's a guard against the common patterns, not
  real understanding of negation, so it won't catch every way a claim can be denied.
- If a test/build result is invalidated because the working tree changed, that trigger
  is currently a bit too broad, any file write in the same turn counts, even ones that
  have nothing to do with the code under test. Not fixed. Doing this properly would mean
  actually knowing which files a test depends on, which is a meaningfully bigger feature
  than a quick patch, and since this fails toward an unnecessary UNKNOWN rather than a
  wrong VERIFIED, it's waiting for real evidence this is actually annoying in practice
  before building that.
- Nothing here stops an agent from writing a command that exits 0 without honestly
  testing anything. checkclaim trusts the exit code as real evidence, it can't tell if
  the command itself was dishonest. There's a partial mitigation already: the automatic
  Stop hook only treats a command as "test" or "build" evidence if it matches a known
  test runner (npm test, pytest, go test, and similar), so a made-up one-liner claiming
  to be the test suite wouldn't get picked up that way. The manual CLI has no such
  guard, it trusts whatever command you explicitly tell it to run, which is reasonable
  since you're the one who typed it. Fully solving this would mean either an LLM judging
  whether a command honestly tests what it claims to (against the whole point of keeping
  the core deterministic) or a much longer hardcoded allowlist, neither is planned.
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

This has been tested against real, independent headless Claude Code sessions (separate
`claude -p` processes, not the same conversation that wrote this code), covering
adversarial scenarios designed to try to trick it, ordinary real coding tasks, and both
install paths described above. It has not produced a false VERIFIED in any of that
testing so far, and that's the one property this project cares about most.

What it hasn't had yet: nobody but me has actually used this on their own project, for
their own reasons. Everything above is closer to "the mechanism holds up under real
conditions" than "someone other than me has found this useful." If you try it, especially
if something looks wrong or annoying, that's genuinely useful information, please open an
issue.

## license

MIT, see LICENSE.
