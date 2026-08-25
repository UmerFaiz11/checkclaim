# Installing checkclaim

If you're a human reading this, the short version is: clone or unzip this folder
somewhere, then ask Claude Code to set it up for you. Paste this into the chat, from
inside the project you want to protect:

> Install checkclaim into this project by following the steps in INSTALL.md at
> /path/to/checkclaim (fill in the real path to wherever you cloned or unzipped it).

Everything below this line is written as direct instructions for whatever agent is
reading it, not as a human-facing tutorial. If you'd rather do it yourself by hand,
follow the same steps, they're the same either way.

---

## Instructions for the agent doing the install

Goal: register `stop_hook.py` as a Stop hook in the **target project** (the one the
user is asking you to protect), not in this checkclaim folder itself.

1. **Find this checkclaim folder's real absolute path on disk.** You'll need it below.
   Don't guess it, resolve it for real (e.g. from where you're reading this file from).

2. **Confirm the target project.** If it's not obvious from context, ask the user which
   project they want this installed into. It's almost always the project they're
   already working in, not the checkclaim folder itself.

3. **Figure out the right Python command.** Run `python3 --version`. If that prints a
   Python 3.x version, use `python3` in the next step. Otherwise try `python --version`,
   and use `python` if that's the one that resolves to Python 3.

4. **Edit `.claude/settings.json` in the target project.** Wrap the path in escaped
   quotes inside the command string, not just a bare path, this matters: if the path
   contains a space anywhere (very common on Windows, e.g. a folder under "My Documents"),
   an unquoted path breaks the command when the shell tries to run it. This has actually
   happened in testing, it's not a hypothetical.
   - If the file doesn't exist, create it with:
     ```json
     {
       "hooks": {
         "Stop": [
           { "hooks": [ { "type": "command", "command": "<python-command> \"<absolute-path>/stop_hook.py\"" } ] }
         ]
       }
     }
     ```
   - If the file exists already, read it first. If it has no `hooks` key, or no
     `hooks.Stop` key, add one the same way, keeping everything else in the file
     untouched.
   - If `hooks.Stop` already exists as an array, **append** a new entry in the same
     shape shown above. Do not remove or rewrite any hook entries that are already
     there, this file may be doing other things you shouldn't disturb.
   - Use the real absolute path from step 1, not a placeholder.

5. **Edit `.gitignore` in the target project.** Add a line `.checkclaim/` if one isn't
   already there. If there's no `.gitignore`, create one with just that line.

6. **Show the user the final `.claude/settings.json`** so they can see exactly what
   changed, and confirm out loud that it's valid JSON.

7. **Tell the user what happens next, briefly:** from now on, every time a Claude Code
   turn ends in this project, checkclaim quietly checks whatever was just claimed
   (tests passed, build succeeded, a file was created, a commit was made) against what
   actually happened, and logs the result to `.checkclaim/verdicts.jsonl` in that
   project. It never blocks or interrupts anything.

**Do not:**
- Install this into the checkclaim folder itself unless that's genuinely what was asked.
- Overwrite any part of `.claude/settings.json` that isn't related to this hook.
- Write a path into the config without first confirming it actually points at
  `stop_hook.py` on disk.
