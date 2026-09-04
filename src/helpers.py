"""
helpers.py - Low-level utility functions: command execution, input prompts,
menu helpers, banners.
"""

import os
import sys
import subprocess


def run(cmd, check=True, shell=True, capture=False, cwd=None, env=None):
    """Run a command (always via shell for complex strings).
    If check=True, exits the script on non-zero return code."""
    display = cmd if isinstance(cmd, str) else " ".join(cmd)
    print(f">>> {display}")
    if capture:
        r = subprocess.run(cmd, shell=shell, capture_output=True, text=True,
                           errors="replace", cwd=cwd, env=env)
        if check and r.returncode != 0:
            print(f"[!!] Command failed (exit {r.returncode}): {display}")
            if r.stderr:
                print(r.stderr)
            sys.exit(1)
        return r
    else:
        r = subprocess.run(cmd, shell=shell, cwd=cwd, env=env)
        if check and r.returncode != 0:
            print(f"[!!] Command failed (exit {r.returncode}): {display}")
            sys.exit(1)
        return r


def run_interactive(cmd, cwd=None):
    """Run a command that needs the terminal (cfdisk, make menuconfig, passwd).
    Does NOT capture output - inherits stdin/stdout/stderr."""
    print(f">>> {cmd}")
    return subprocess.run(cmd, shell=True, cwd=cwd)


def ask(prompt, default=None):
    """Prompt for a string. Empty input returns default (if non-empty)."""
    suffix = f" [{default}]" if default not in (None, "") else ""
    while True:
        try:
            s = input(f"{prompt}{suffix}: ").strip()
        except EOFError:
            print()
            sys.exit(1)
        if not s and default not in (None, ""):
            return default
        return s


def confirm(prompt, default_yes=False):
    d = "Y/n" if default_yes else "y/N"
    while True:
        try:
            s = input(f"{prompt} [{d}]: ").strip().lower()
        except EOFError:
            print()
            sys.exit(1)
        if not s:
            return default_yes
        if s in ("y", "yes"):
            return True
        if s in ("n", "no"):
            return False


def choose(prompt, options, default_index=0):
    """options: list of (label, value) tuples. Returns (value, label, index)."""
    print(f"\n  {prompt}")
    for i, opt in enumerate(options, 1):
        label = opt[0] if isinstance(opt, tuple) else opt
        mark = " *" if i == default_index + 1 else ""
        print(f"   [{i}] {label}{mark}")
    while True:
        try:
            s = input(f"  Select [1-{len(options)}] (default {default_index+1}): ").strip()
        except EOFError:
            print()
            sys.exit(1)
        if not s:
            idx = default_index
        elif s.isdigit() and 1 <= int(s) <= len(options):
            idx = int(s) - 1
        else:
            print("  Invalid choice, try again.")
            continue
        chosen = options[idx]
        if isinstance(chosen, tuple):
            return chosen[1], chosen[0], idx
        return chosen, chosen, idx


def pause(msg="Press Enter to continue..."):
    try:
        input(msg)
    except EOFError:
        print()


def banner(title):
    w = 66
    print("\n" + "=" * w)
    print(f"  {title}")
    print("=" * w)
