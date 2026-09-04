#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
main.py - Entry point for the Gentoo Linux Installer (multi-file version).

Usage:
    python3 main.py            # full interactive flow (LiveCD)
    python3 main.py --chroot   # internal: re-run inside chroot

This is the modular version of install.py, split into:
    config.py        - constants & global CONFIG dict
    helpers.py       - run/ask/confirm/choose/banner utilities
    detector.py      - chroot/cpu/swap/mount detection
    stage3.py        - mirror stage3 variant & file listing
    menu.py          - archinstall/Pentoo-style main menu
    livecd.py        - LiveCD phase (mount/stage3/make.conf/chroot entry)
    chroot_phase.py  - chroot phase (sync/kernel/desktop/tools/user/grub)
    finalize.py      - umount + reboot/poweroff
"""

import sys
import os

# Ensure the src directory is on sys.path so sibling modules import cleanly.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from helpers import banner
from detector import detect_chroot


def main():
    args = sys.argv[1:]
    is_chroot = "--chroot" in args or detect_chroot()

    banner("Gentoo Linux Installer")
    print("  Pentoo/archinstall-style installer for Gentoo Linux.")
    print("  OpenRC | UEFI | dracut | multi-desktop")
    print()

    if is_chroot:
        from chroot_phase import run_chroot_phase
        run_chroot_phase()
    else:
        from livecd import run_livecd_phase
        run_livecd_phase()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n[!!] Interrupted by user. Aborting.")
        sys.exit(130)
