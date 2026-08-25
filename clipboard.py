"""
Reads whatever's currently on the system clipboard.

Meant for the "copy Claude's answer out of a chat window, then check
it" workflow, so you don't have to retype or re-paste the claim text
as a command line argument. No third-party dependency, just shells out
to whatever the OS already has for this.
"""

import platform
import subprocess


def read():
    """Returns (text, error). Exactly one of them is not None."""
    system = platform.system()
    try:
        if system == "Windows":
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
                capture_output=True, text=True, timeout=5,
            )
        elif system == "Darwin":
            proc = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=5)
        else:
            proc = _read_linux_clipboard()
            if proc is None:
                return None, "no clipboard tool found (tried xclip, xsel, wl-paste)"
    except FileNotFoundError:
        return None, f"no clipboard tool available on {system}"
    except Exception as e:
        return None, f"couldn't read the clipboard: {e}"

    if proc.returncode != 0:
        return None, f"clipboard read failed: {proc.stderr.strip() or 'unknown error'}"

    text = proc.stdout.rstrip("\r\n")
    if not text:
        return None, "clipboard is empty"
    return text, None


def _read_linux_clipboard():
    for cmd in (
        ["xclip", "-selection", "clipboard", "-o"],
        ["xsel", "--clipboard", "--output"],
        ["wl-paste"],
    ):
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            return proc
        except FileNotFoundError:
            continue
    return None
