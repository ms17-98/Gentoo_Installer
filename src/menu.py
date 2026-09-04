"""
menu.py - The archinstall/Pentoo-style main menu and sub-menus.
"""

import os
import re
import sys

from config import CONFIG, MIRRORS, DESKTOPS, KERNEL_METHODS, FILESYSTEMS
from helpers import ask, confirm, choose, pause, banner
from detector import list_block_devices, detect_disk_partitions, classify_partitions
from stage3 import fetch_stage3_variants, fetch_stage3_files, sort_variants


def menu_show_summary():
    """Print the current configuration as a summary table."""
    dv = CONFIG["desktop"]
    dv_label = DESKTOPS[dv][0] if dv in DESKTOPS else dv
    km = CONFIG["kernel_method"]
    print()
    print("  +----------------------------------------------------------+")
    print("  |  Current configuration                                   |")
    print("  +----------------------------------------------------------+")
    print(f"  |  Disk (cfdisk target) : {CONFIG['disk_dev'] or '(not set)'}")

    parts = CONFIG.get("partitions", [])
    if parts:
        print(f"  |  Partitions ({len(parts)}):")
        for p in parts:
            role = p.get("role", "?")
            mnt = p.get("mountpoint") or "-"
            print(f"  |    {p['device']:20s}  {role:6s}  {p.get('fstype','?'):8s}  -> {mnt}")
    else:
        print(f"  |  Root partition        : {CONFIG['root_part'] or '(not set)'}")
        print(f"  |  EFI/boot partition    : {CONFIG['boot_part'] or '(not set)'}")
        print(f"  |  Swap partition        : {CONFIG['swap_part'] or '(none)'}")

    print(f"  |  Mirror                : {CONFIG['mirror_name']}")
    print(f"  |  Stage3                : {CONFIG['stage3_file'] or '(auto-select latest)'}")
    print(f"  |  Timezone              : {CONFIG['timezone']}")
    print(f"  |  Hostname              : {CONFIG['hostname']}")
    print(f"  |  Username              : {CONFIG['username']}")
    print(f"  |  Desktop               : {dv_label}")
    print(f"  |  Kernel config         : {km}")
    print("  +----------------------------------------------------------+")


def _print_partition_table(parts):
    """Pretty-print a list of partition dicts."""
    print(f"\n  {'Device':20s}  {'Size':>8s}  {'PartType':22s}  {'FSType':8s}")
    print(f"  {'-'*20}  {'-'*8}  {'-'*22}  {'-'*8}")
    for p in parts:
        print(f"  {p.get('device',''):20s}  {p.get('size',''):>8s}  "
              f"{(p.get('part_type','') or ''):22s}  "
              f"{(p.get('fstype','') or ''):8s}")


def _ask_filesystem(prompt, default="ext4"):
    """Ask the user to pick a filesystem type. Returns the fs name string."""
    options = FILESYSTEMS
    cur_idx = 0
    for i, (_, val) in enumerate(FILESYSTEMS):
        if val == default:
            cur_idx = i
            break
    val, label, _ = choose(prompt, options, default_index=cur_idx)
    return val


_MOUNTPOINT_RE = re.compile(r'^/[A-Za-z0-9_./-]*$')


def _valid_mountpoint(mnt):
    """A mountpoint must be an absolute path of safe characters.

    It later flows into shell mount commands, so reject anything that could
    be interpreted by a shell (spaces, ;, |, &, $, backticks, ...).
    """
    return bool(_MOUNTPOINT_RE.match(mnt))


def _build_partitions_from_classified(disk, classified, interactive=True):
    """Build the CONFIG['partitions'] list from a classification dict.

    For 'root' and 'data' partitions, ask the user for the filesystem type
    (and mountpoint for data partitions).  EFI is always vfat, swap is always swap.
    """
    parts = []

    # ---- EFI (always vfat / FAT32) --------------------------------------
    efi = classified.get("efi")
    if efi:
        parts.append({
            "device":     efi["device"],
            "role":       "efi",
            "fstype":     "vfat",
            "mountpoint": "/boot",
            "size":       efi.get("size", ""),
            "part_type":  efi.get("part_type", ""),
        })
        print(f"\n  EFI partition detected: {efi['device']} ({efi.get('size','')})")
        print(f"  -> Filesystem: vfat (FAT32, fixed for UEFI)")

    # ---- Swap (always swap) --------------------------------------------
    swap = classified.get("swap")
    if swap:
        parts.append({
            "device":     swap["device"],
            "role":       "swap",
            "fstype":     "swap",
            "mountpoint": None,
            "size":       swap.get("size", ""),
            "part_type":  swap.get("part_type", ""),
        })
        print(f"\n  Swap partition detected: {swap['device']} ({swap.get('size','')})")
        print(f"  -> Filesystem: swap")

    # ---- Root ------------------------------------------------------------
    root = classified.get("root")
    if root:
        default_fs = "ext4"
        if root.get("fstype") and root["fstype"] in [v for _, v in FILESYSTEMS]:
            default_fs = root["fstype"]
        if interactive:
            print(f"\n  Root partition detected: {root['device']} ({root.get('size','')})")
            fs = _ask_filesystem("  Select filesystem for root partition", default_fs)
        else:
            fs = default_fs
        parts.append({
            "device":     root["device"],
            "role":       "root",
            "fstype":     fs,
            "mountpoint": "/",
            "size":       root.get("size", ""),
            "part_type":  root.get("part_type", ""),
        })

    # ---- Data partitions (any number) -----------------------------------
    for i, dp in enumerate(classified.get("data", [])):
        default_fs = "ext4"
        if dp.get("fstype") and dp["fstype"] in [v for _, v in FILESYSTEMS]:
            default_fs = dp["fstype"]
        if interactive:
            print(f"\n  Data partition {i+1} detected: {dp['device']} ({dp.get('size','')})")
            fs = _ask_filesystem(
                f"  Select filesystem for {dp['device']}", default_fs)
            mnt = ask(
                f"  Mountpoint for {dp['device']} (e.g. /home, /var, /opt; empty = skip)",
                "")
            if not mnt:
                print(f"  Skipping {dp['device']} (no mountpoint given).")
                continue
            if not mnt.startswith("/"):
                mnt = "/" + mnt
            if not _valid_mountpoint(mnt):
                print(f"  [!] Invalid mountpoint '{mnt}' (no spaces or shell chars).")
                print(f"  Skipping {dp['device']}.")
                continue
        else:
            fs = default_fs
            mnt = f"/data{i+1}"
        parts.append({
            "device":     dp["device"],
            "role":       "data",
            "fstype":     fs,
            "mountpoint": mnt,
            "size":       dp.get("size", ""),
            "part_type":  dp.get("part_type", ""),
        })

    return parts


def _manual_partition_entry():
    """Fallback: let the user manually enter partition device paths.

    Asks for EFI, root, swap, and any number of additional partitions.
    """
    parts = []

    # EFI
    efi_dev = ask("EFI/boot partition (e.g. /dev/sda1, /dev/nvme0n1p1)", "")
    if efi_dev:
        if not os.path.exists(efi_dev):
            print(f"[!] {efi_dev} does not exist; skipping EFI.")
        else:
            parts.append({
                "device": efi_dev, "role": "efi", "fstype": "vfat",
                "mountpoint": "/boot", "size": "", "part_type": "",
            })

    # Root
    root_dev = ask("Root partition (e.g. /dev/sda3, /dev/nvme0n1p3)", "")
    if not root_dev or not os.path.exists(root_dev):
        print(f"[!!] Root partition is required and must exist.")
        pause()
        return None
    fs = _ask_filesystem("  Select filesystem for root partition", "ext4")
    parts.append({
        "device": root_dev, "role": "root", "fstype": fs,
        "mountpoint": "/", "size": "", "part_type": "",
    })

    # Swap
    swap_dev = ask("Swap partition (leave empty if none)", "")
    if swap_dev:
        if not os.path.exists(swap_dev):
            print(f"[!] {swap_dev} does not exist; ignoring swap.")
        else:
            parts.append({
                "device": swap_dev, "role": "swap", "fstype": "swap",
                "mountpoint": None, "size": "", "part_type": "",
            })

    # Additional data partitions
    idx = 1
    while True:
        extra = ask(f"Additional partition {idx} (leave empty to finish)", "")
        if not extra:
            break
        if not os.path.exists(extra):
            print(f"[!] {extra} does not exist; skipping.")
            continue
        fs = _ask_filesystem(f"  Select filesystem for {extra}", "ext4")
        mnt = ask(f"  Mountpoint for {extra} (e.g. /home, /var)", "")
        if not mnt:
            print(f"  Skipping {extra} (no mountpoint).")
            idx += 1
            continue
        if not mnt.startswith("/"):
            mnt = "/" + mnt
        if not _valid_mountpoint(mnt):
            print(f"  [!] Invalid mountpoint '{mnt}' (no spaces or shell chars).")
            print(f"  Skipping {extra}.")
            idx += 1
            continue
        parts.append({
            "device": extra, "role": "data", "fstype": fs,
            "mountpoint": mnt, "size": "", "part_type": "",
        })
        idx += 1

    return parts


def menu_disk():
    """Sub-menu: disk selection, auto-detect partitions, choose filesystems."""
    banner("Disk & Partitions")
    print("Current block devices:")
    print(list_block_devices())

    # ---- optional cfdisk ------------------------------------------------
    if confirm("\nLaunch cfdisk to partition a disk now?", default_yes=False):
        dev = ask("Disk device to partition (e.g. /dev/sda, /dev/nvme0n1)", "/dev/sda")
        if not os.path.exists(dev):
            print(f"[!!] {dev} does not exist.")
            return
        print("\n  In cfdisk: choose gpt label, then create:")
        print("    - EFI System partition  (~1G)")
        print("    - Linux swap            (~4G)")
        print("    - Linux filesystem      (rest, for root)")
        print("    - (optional more partitions for /home, /var, etc.)")
        print("  Write, then Quit.\n")
        pause("Press Enter to launch cfdisk...")
        from helpers import run_interactive
        run_interactive(f"cfdisk {dev}")
        print("\nUpdated block devices:")
        print(list_block_devices())

    # ---- disk device ----------------------------------------------------
    CONFIG["disk_dev"] = ask(
        "Disk device (e.g. /dev/sda, /dev/nvme0n1)",
        CONFIG.get("disk_dev") or "/dev/sda")

    disk = CONFIG["disk_dev"]
    if not disk or not os.path.exists(disk):
        print(f"[!!] Disk {disk} does not exist.")
        pause()
        return

    # ---- auto-detect partitions -----------------------------------------
    print(f"\n  Scanning partitions on {disk} ...")
    raw_parts = detect_disk_partitions(disk)

    if not raw_parts:
        print("[!] Could not auto-detect partitions (lsblk/fdisk unavailable?).")
        print("    Falling back to manual entry.\n")
        parts = _manual_partition_entry()
        if not parts:
            return
    else:
        print(f"\n  Detected {len(raw_parts)} partition(s) on {disk}:")
        _print_partition_table(raw_parts)

        # classify
        classified = classify_partitions(raw_parts)

        if not classified["root"]:
            print("\n[!] Could not identify a root partition.")
            print("    Falling back to manual entry.\n")
            parts = _manual_partition_entry()
            if not parts:
                return
        else:
            parts = _build_partitions_from_classified(
                disk, classified, interactive=True)

    if not parts:
        print("[!!] No partitions configured.")
        pause()
        return

    # ---- summary & confirm ----------------------------------------------
    banner("Partition Plan")
    print(f"  Disk: {disk}\n")
    print(f"  {'Device':20s}  {'Role':6s}  {'FS':8s}  {'Mountpoint':20s}")
    print(f"  {'-'*20}  {'-'*6}  {'-'*8}  {'-'*20}")
    for p in parts:
        if p["role"] == "swap":
            mnt = "(swap)"
        else:
            mnt = p.get("mountpoint", "")
        print(f"  {p['device']:20s}  {p['role']:6s}  {p['fstype']:8s}  {mnt:20s}")

    # validation
    has_root = any(p["role"] == "root" for p in parts)
    has_efi  = any(p["role"] == "efi"  for p in parts)
    if not has_root:
        print("\n[!!] A root partition is required.")
        pause()
        return
    if not has_efi:
        print("\n[!] No EFI partition detected. UEFI boot requires an EFI partition.")
        if not confirm("Continue without EFI partition?", default_yes=False):
            return

    if confirm("\nConfirm this partition plan?", default_yes=True):
        CONFIG["partitions"] = parts
        # backward-compatible fields
        CONFIG["root_part"] = next(
            (p["device"] for p in parts if p["role"] == "root"), None)
        CONFIG["boot_part"] = next(
            (p["device"] for p in parts if p["role"] == "efi"), None)
        CONFIG["swap_part"] = next(
            (p["device"] for p in parts if p["role"] == "swap"), "")
        print("\n  [OK] Partition plan saved.")
    else:
        print("  Partition plan not saved.")


def menu_mirror():
    """Sub-menu: mirror selection."""
    options = [(label, url) for label, url in MIRRORS]
    cur_idx = 0
    for i, (_, url) in enumerate(MIRRORS):
        if url == CONFIG["mirror"]:
            cur_idx = i
            break
    url, label, _ = choose("Select a mirror", options, default_index=cur_idx)
    CONFIG["mirror"] = url
    CONFIG["mirror_name"] = label


def menu_stage3():
    """Sub-menu: stage3 variant + tarball selection."""
    variants = fetch_stage3_variants(CONFIG["mirror"])
    if not variants:
        print("[!] Could not fetch stage3 variant list. Check network/mirror.")
        pause()
        return

    variants = sort_variants(variants)
    options = [(label, vdir) for vdir, label in variants]
    vdir, vlabel, _ = choose("Select stage3 variant (openrc recommended)",
                             options, default_index=0)

    files = fetch_stage3_files(CONFIG["mirror"], vdir)
    if not files:
        print(f"[!] No .tar.xz found in {vdir}.")
        pause()
        return
    if len(files) == 1:
        name, url = files[0]
        print(f"\n  Only one tarball found: {name}")
    else:
        options = [(name, url) for name, url in files]
        url, name, _ = choose("Select stage3 tarball", options, default_index=0)
    CONFIG["stage3_url"]  = url
    CONFIG["stage3_file"] = name
    print(f"\n  [OK] Stage3: {name}")


def menu_timezone():
    tz = ask("Timezone (e.g. Asia/Shanghai, Europe/London, America/New_York)",
             CONFIG.get("timezone", "Asia/Shanghai"))
    CONFIG["timezone"] = tz


def menu_hostname():
    hn = ask("Hostname", CONFIG.get("hostname", "gentoo"))
    CONFIG["hostname"] = hn


def menu_username():
    un = ask("Username for the new user", CONFIG.get("username", "gentoo"))
    if not re.match(r'^[a-z_][a-z0-9_-]*$', un):
        print("[!] Invalid username (must start with letter/underscore,")
        print("    lowercase alnum, dashes, underscores only).")
        pause()
        return
    CONFIG["username"] = un


def menu_desktop():
    options = [(label, key) for key, (label, _, _) in DESKTOPS.items()]
    cur_idx = 0
    for i, (key, _) in enumerate(DESKTOPS.items()):
        if key == CONFIG["desktop"]:
            cur_idx = i
            break
    key, label, _ = choose("Select desktop environment", options, default_index=cur_idx)
    CONFIG["desktop"] = key


def menu_kernel():
    cur_idx = 0
    for i, (_, v) in enumerate(KERNEL_METHODS):
        if v == CONFIG["kernel_method"]:
            cur_idx = i
            break
    v, label, _ = choose("Select kernel configuration method",
                         KERNEL_METHODS, default_index=cur_idx)
    CONFIG["kernel_method"] = v


def main_menu():
    """The archinstall/Pentoo-style main menu. Loops until user installs or quits."""
    menu_items = [
        ("Disk & partitions",        menu_disk),
        ("Mirror",                   menu_mirror),
        ("Stage3 tarball",           menu_stage3),
        ("Timezone",                 menu_timezone),
        ("Hostname",                 menu_hostname),
        ("Username",                 menu_username),
        ("Desktop environment",      menu_desktop),
        ("Kernel config method",     menu_kernel),
    ]

    while True:
        banner("Gentoo Linux Installer - Main Menu")
        print("  Configure each option below. Defaults are pre-filled.")
        print("  When ready, choose [Install] to begin the automated install.\n")
        menu_show_summary()
        print()
        for i, (label, _) in enumerate(menu_items, 1):
            print(f"   [{i}] {label}")
        print(f"   [{len(menu_items)+1}] INSTALL - begin automated installation")
        print(f"   [q] Quit")
        try:
            s = input(f"\n  Select [1-{len(menu_items)+1}/q]: ").strip().lower()
        except EOFError:
            print()
            sys.exit(1)

        if s == "q":
            print("Aborting.")
            sys.exit(0)

        if not s.isdigit() or not (1 <= int(s) <= len(menu_items) + 1):
            print("  Invalid choice.")
            pause()
            continue

        idx = int(s)
        if idx <= len(menu_items):
            menu_items[idx - 1][1]()
            continue

        # INSTALL
        missing = []
        if not CONFIG.get("partitions"):
            missing.append("Disk & partitions (run menu first)")
        else:
            if not any(p["role"] == "root" for p in CONFIG["partitions"]):
                missing.append("Root partition")
        if not CONFIG["stage3_url"]:
            print("\n  Stage3 not selected yet. Auto-fetching list...")
            menu_stage3()
            if not CONFIG["stage3_url"]:
                missing.append("Stage3 tarball")
        if missing:
            print(f"\n[!!] Cannot install, missing: {', '.join(missing)}")
            pause()
            continue

        banner("Ready to Install")
        menu_show_summary()
        print("\n  This will ERASE the contents of the target partitions")
        print("  and install Gentoo Linux. Make sure your data is backed up.")
        if confirm("\n  Proceed with installation?", default_yes=False):
            return
        print("  Installation cancelled.")
