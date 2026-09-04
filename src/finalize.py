"""
finalize.py - Final phase: unmount everything, swapoff, reboot/poweroff.
Runs on the LiveCD after chroot returns.
"""

from config import CONFIG
from helpers import run, ask, banner
from detector import detect_swap_devices, detect_mounted_under


def phase_unmount_and_finish():
    banner("Final: unmount & reboot")
    mp = CONFIG["mountpoint"]

    # 1. swapoff all active swaps (auto-detected, not hardcoded)
    swaps = detect_swap_devices()
    if swaps:
        print(f"Detected {len(swaps)} active swap device(s):")
        for s in swaps:
            print(f"  - {s}")
        for s in swaps:
            run(f"swapoff {s}", check=False)
    else:
        print("No active swap devices.")

    # 2. umount everything under /mnt/gentoo
    mounts = detect_mounted_under(mp)
    if mounts:
        print(f"\nDetected {len(mounts)} mountpoint(s) under {mp}:")
        for m in mounts:
            print(f"  - {m}")
        run(f"umount -R {mp}", check=False)
    else:
        print(f"No mountpoints under {mp}.")

    print("\n=== Installation finished! ===\n")
    action = ask("Reboot (r) or Poweroff (p)?", "r").lower()
    if action.startswith("r"):
        run("reboot", check=False)
    elif action.startswith("p"):
        run("poweroff", check=False)
    else:
        print("Unknown choice. Reboot or poweroff manually.")
