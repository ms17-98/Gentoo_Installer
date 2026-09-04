"""
livecd.py - LiveCD phase: format partitions, mount partitions, download stage3,
generate make.conf, configure repos.conf, mount pseudo-fs, enter chroot.
"""

import os
import re
import sys
import json
import shutil
import subprocess
from pathlib import Path

from config import CONFIG, PORTAGE_SYNC, FORMAT_COMMANDS
from helpers import run, banner, confirm
from detector import detect_cpu_cores


def phase_format_partitions():
    """Format all configured partitions according to their fstype.

    Iterates over CONFIG['partitions'] (any number of entries) and runs
    the appropriate mkfs command for each.  EFI -> vfat, swap -> mkswap,
    root/data -> user-selected filesystem.
    """
    banner("Step 0: Format partitions")
    parts = CONFIG.get("partitions", [])
    if not parts:
        print("[!] No partitions configured; skipping format step.")
        return

    print(f"\n  {len(parts)} partition(s) will be formatted:\n")
    print(f"  {'Device':20s}  {'Role':6s}  {'FS':8s}  {'Size':>8s}  Mount")
    print(f"  {'-'*20}  {'-'*6}  {'-'*8}  {'-'*8}  {'-'*20}")
    for p in parts:
        mnt = p.get("mountpoint") or "(swap)"
        print(f"  {p['device']:20s}  {p['role']:6s}  {p['fstype']:8s}  "
              f"{p.get('size',''):>8s}  {mnt}")

    print("\n  [!!] This will ERASE ALL DATA on the listed partitions!")
    if not confirm("\n  Proceed with formatting?", default_yes=False):
        print("  Formatting skipped. Will mount existing filesystems as-is.")
        return

    for p in parts:
        dev   = p["device"]
        fs    = p["fstype"]
        role  = p["role"]
        cmd   = FORMAT_COMMANDS.get(fs)

        if not cmd:
            print(f"\n  [!] Unknown filesystem '{fs}' for {dev}; skipping.")
            continue

        if not os.path.exists(dev):
            print(f"\n  [!] Device {dev} not found; skipping.")
            continue

        label = f"{role.upper()} {dev} -> {fs}"
        print(f"\n  Formatting {label} ...")
        run(f"{cmd} {dev}", check=False)

    print("\n[OK] Partition formatting complete.")


def phase_mount_partitions():
    """Mount all configured partitions under the Gentoo mountpoint.

    Mount order:
      1. root partition at CONFIG['mountpoint']
      2. data/EFI partitions sorted by mountpoint depth (shallow first)
      3. swap activation (last)
    """
    banner("Step 1: Mount partitions")
    mp = CONFIG["mountpoint"]
    parts = CONFIG.get("partitions", [])

    if not parts:
        # backward-compatible fallback for older configs without 'partitions'
        run(f"mkdir -p {mp}")
        if CONFIG.get("root_part"):
            run(f"mount {CONFIG['root_part']} {mp}")
        if CONFIG.get("boot_part"):
            run(f"mkdir -p {mp}/boot")
            run(f"mount {CONFIG['boot_part']} {mp}/boot")
        if CONFIG.get("swap_part"):
            run(f"swapon {CONFIG['swap_part']}", check=False)
        print("[OK] Partitions mounted (legacy mode).")
        return

    # ---- sort: root first, then data by depth, swap last ---------------
    def sort_key(p):
        role = p.get("role", "")
        mnt = p.get("mountpoint") or ""
        if role == "root":
            return (0, 0, mnt)
        elif role == "swap":
            return (2, 0, mnt)
        else:
            # deeper mountpoints mounted later (e.g. /home before /home/user)
            return (1, len(mnt.rstrip("/")), mnt)

    sorted_parts = sorted(parts, key=sort_key)

    for p in sorted_parts:
        dev  = p["device"]
        role = p.get("role", "")
        mnt  = p.get("mountpoint")
        fs   = p.get("fstype", "")

        if role == "swap":
            print(f"  Activating swap on {dev} ...")
            run(f"swapon {dev}", check=False)
            continue

        if not mnt:
            continue

        # map mountpoint to target under our mountpoint
        if mnt == "/":
            target = mp
        else:
            target = f"{mp}{mnt}"

        run(f"mkdir -p {target}")
        # use appropriate mount options
        if fs == "btrfs":
            run(f"mount -o compress-force=zstd {dev} {target}", check=False)
        else:
            run(f"mount {dev} {target}")
        print(f"  [OK] {dev} -> {target}  ({fs})")

    print("[OK] Partitions mounted.")


def phase_download_stage3():
    banner("Step 2: Download & extract stage3")
    mp = CONFIG["mountpoint"]
    os.chdir(mp)
    url = CONFIG["stage3_url"]
    fname = CONFIG["stage3_file"]
    if not os.path.exists(fname):
        print(f"Downloading {fname} ...")
        run(f"wget -c {url}")
    else:
        print(f"{fname} already exists; skipping download.")
    print(f"\nExtracting {fname} ...")
    run(f"tar xpvf {fname} --xattrs-include='*.*' --numeric-owner")
    print("[OK] Stage3 extracted.")


def phase_makeconf():
    banner("Step 3: Generate make.conf")
    cores  = CONFIG["cpu_cores"]
    mirror = CONFIG["mirror"]
    path = f"{CONFIG['mountpoint']}/etc/portage/make.conf"

    # Per-desktop USE flags.  A hardcoded negative USE list (e.g. "-gtk -kde")
    # would break the very desktop the user selected, so derive it from
    # CONFIG['desktop'] instead.
    DESKTOP_USE = {
        "none":     'USE="-X"',
        "xfce4":    'USE="X gtk"',
        "kde":      'USE="X qt6 kde"',
        "gnome":    'USE="X gtk gnome"',
        "cinnamon": 'USE="X gtk"',
        "mate":     'USE="X gtk"',
        "i3":       'USE="X"',
        "bspwm":    'USE="X"',
        "hyprland": 'USE="X wayland"',
    }
    desktop = CONFIG.get("desktop", "none")
    use_line = DESKTOP_USE.get(desktop, 'USE="-X"')

    content = f"""# =============================================================================
# make.conf - generated by gentoo-installer
# =============================================================================
# CPU: detected {cores} cores
# Mirror: {mirror}

COMMON_FLAGS="-march=native -O2 -pipe"
CFLAGS="${{COMMON_FLAGS}}"
CXXFLAGS="${{COMMON_FLAGS}}"
FCFLAGS="${{COMMON_FLAGS}}"
FFLAGS="${{COMMON_FLAGS}}"

# Parallel build & emerge.
MAKEOPTS="-j{cores} --jobs={cores}"
EMERGE_DEFAULT_OPTS="--jobs={cores} --keep-going"

# NOTE: This stage was built with the bindist USE flag enabled.
# Desktop: {desktop}
{use_line}

# Build output language: keep English for clean logs.
LC_MESSAGES=C.utf8
LINGUAS="en"

GENTOO_MIRRORS="{mirror}"

ACCEPT_LICENSE="*"

# CPU feature flags (run `cpuid2cpuflags` after first boot to fill).
# CPU_FLAGS_X86="..."

# Video cards - adjust to your hardware.
# VIDEO_CARDS="intel i965 iris amdgpu radeon nouveau"
# INPUT_DEVICES="libinput"

FEATURES="buildpkg parallel-fetch"
"""
    Path(path).write_text(content)
    print(f"[OK] Wrote {path}")


def phase_repos_conf():
    banner("Step 4: Configure Portage repo & DNS")
    mp = CONFIG["mountpoint"]
    mirror = CONFIG["mirror"]
    sync_uri = PORTAGE_SYNC.get(mirror, mirror.rstrip("/") + "-portage")

    run(f"mkdir -p {mp}/etc/portage/repos.conf")
    src = f"{mp}/usr/share/portage/config/repos.conf"
    dst = f"{mp}/etc/portage/repos.conf/gentoo.conf"
    if os.path.exists(src):
        run(f"cp {src} {dst}")
    else:
        Path(dst).write_text(
            "[gentoo]\n"
            "location = /var/db/repos/gentoo\n"
            "sync-type = git\n"
            f"sync-uri = {sync_uri}\n"
            "auto-sync = yes\n"
            "sync-depth = 1\n"
        )

    txt = Path(dst).read_text()
    txt = re.sub(r'sync-uri\s*=.*', f'sync-uri = {sync_uri}', txt)
    txt = re.sub(r'sync-type\s*=.*', 'sync-type = git', txt)
    Path(dst).write_text(txt)
    print(f"[OK] repos.conf sync-uri = {sync_uri}")

    if os.path.exists("/etc/resolv.conf"):
        run(f"cp /etc/resolv.conf {mp}/etc/resolv.conf")
        print("[OK] Copied /etc/resolv.conf")
    else:
        print("[!] /etc/resolv.conf not found on livecd.")


def phase_mount_pseudofs():
    banner("Step 5: Mount pseudo-filesystems")
    mp = CONFIG["mountpoint"]
    for c in [
        f"mount --types proc /proc {mp}/proc",
        f"mount --rbind /sys {mp}/sys",
        f"mount --make-rslave {mp}/sys",
        f"mount --rbind /dev {mp}/dev",
        f"mount --make-rslave {mp}/dev",
        f"mount --bind /run {mp}/run",
    ]:
        run(c, check=False)
    print("[OK] Pseudo-filesystems mounted.")


def _find_main_py_source():
    """Locate the main.py file relative to livecd.py's location.

    Supports:
      - Normal source mode (running from cloned repo / src/ layout)
      - PyInstaller one-file mode (running from bundled executable)

    Returns absolute path to main.py, or None if not found.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))

    # ---- PyInstaller one-file mode -------------------------------------
    # When bundled with PyInstaller, sys._MEIPASS is the temp extraction dir.
    # If the .py files were included as data files, they land here (or in
    # a subdir like src/ depending on the --add-data spec).
    # ----------------------------------------------------------------------
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        meipass = sys._MEIPASS
        candidates = [
            os.path.join(meipass, "main.py"),
            os.path.join(meipass, "src", "main.py"),
        ]
        for c in candidates:
            if os.path.isfile(c):
                return os.path.abspath(c)
        return None

    # ---- Normal source mode ---------------------------------------------
    candidates = [
        os.path.join(script_dir, "main.py"),
        os.path.join(os.path.dirname(script_dir), "main.py"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return os.path.abspath(c)
    return None


def phase_enter_chroot():
    banner("Step 6: Enter chroot")
    mp = CONFIG["mountpoint"]
    Path(f"{mp}/.gentoo_installer_chroot").write_text("1\n")

    # ---------------------------------------------------------------------
    # Stage A: create the chroot-side install dir
    # ---------------------------------------------------------------------
    script_dir = os.path.dirname(os.path.abspath(__file__))
    chroot_dir = f"{mp}/root/gentoo-installer"
    print(f"\n  Preparing installer dir inside chroot: {chroot_dir}")
    run(f"mkdir -p {chroot_dir}", check=False)

    # ---------------------------------------------------------------------
    # Stage B: copy main.py FIRST (it's the chroot entry point -- must exist
    #          before any other step tries to invoke it).
    # ---------------------------------------------------------------------
    main_py_src = _find_main_py_source()
    main_py_dst = f"{chroot_dir}/main.py"
    if main_py_src is None:
        is_pyinstaller = getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')
        print(f"[!!] FATAL: cannot locate main.py on the LiveCD side.")
        print(f"    Looked at:")
        if is_pyinstaller:
            print(f"      - {os.path.join(sys._MEIPASS, 'main.py')}")
            print(f"      - {os.path.join(sys._MEIPASS, 'src', 'main.py')}")
            print(f"")
            print(f"    [HINT] This is a PyInstaller-bundled executable.")
            print(f"    All .py source files must be included as data files at build time:")
            print(f"")
            print(f"      pyinstaller --onefile --add-data 'src/*.py:src' main.py")
            print(f"")
            print(f"    (Or ':.' instead of ':src' if your PyInstaller spec puts them")
            print(f"     at the root of the extraction dir.)")
        else:
            print(f"      - {os.path.join(script_dir, 'main.py')}")
            print(f"      - {os.path.join(os.path.dirname(script_dir), 'main.py')}")
        sys.exit(1)

    shutil.copy2(main_py_src, main_py_dst)
    print(f"  [OK] Copied main.py:")
    print(f"        from: {main_py_src}")
    print(f"        to:   {main_py_dst}")

    # ---------------------------------------------------------------------
    # Stage C: copy all sibling .py files (helpers / config / detector / etc.)
    #          so chroot_phase can `from helpers import run` etc.
    # ---------------------------------------------------------------------
    copied_siblings = 0

    # Determine source directories for sibling modules.
    # In PyInstaller mode, files may be directly in sys._MEIPASS or under
    # a subdir (e.g. src/) depending on the --add-data spec.
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        src_dirs = [sys._MEIPASS]
        alt = os.path.join(sys._MEIPASS, "src")
        if os.path.isdir(alt):
            src_dirs.append(alt)
    else:
        src_dirs = [script_dir]

    for src_dir in src_dirs:
        if not os.path.isdir(src_dir):
            continue
        for fname in sorted(os.listdir(src_dir)):
            if not fname.endswith(".py") or fname == "main.py":
                continue
            src = os.path.join(src_dir, fname)
            if not os.path.isfile(src):
                continue
            dst = f"{chroot_dir}/{fname}"
            try:
                shutil.copy2(src, dst)
                copied_siblings += 1
            except OSError as e:
                print(f"  [!] Failed to copy {fname}: {e}")
        if copied_siblings > 0:
            break  # found and copied from this directory, skip remaining alt dirs

    print(f"  [OK] Copied {copied_siblings} sibling .py module(s) into {chroot_dir}")

    # ---------------------------------------------------------------------
    # Stage D: forward config via JSON
    # ---------------------------------------------------------------------
    cfg_copy = {k: v for k, v in CONFIG.items()}
    cfg_copy["in_chroot"] = True
    Path(f"{chroot_dir}/.installer_config.json").write_text(
        json.dumps(cfg_copy, indent=2)
    )
    print(f"  [OK] Wrote config: {chroot_dir}/.installer_config.json")

    # ---------------------------------------------------------------------
    # Stage E: sanity-check main.py is actually at the destination BEFORE
    #          entering chroot -- bail out clearly if not.
    # ---------------------------------------------------------------------
    if not os.path.isfile(main_py_dst):
        print(f"[!!] FATAL: {main_py_dst} still missing after copy step.")
        print(f"    Check that {mp} is writable and that the target")
        print(f"    filesystem is mounted (mount | grep {mp}).")
        sys.exit(1)
    print(f"  [OK] Verified {main_py_dst} exists; entering chroot...\n")

    # ---------------------------------------------------------------------
    # Stage F: enter chroot and re-run main.py with --chroot
    # ---------------------------------------------------------------------
    cmd = (
        f"chroot {mp} /bin/bash -c "
        f"'cd /root/gentoo-installer && /usr/bin/env -i HOME=/root TERM=$TERM "
        f"PATH=/usr/sbin:/usr/bin:/sbin:/bin "
        f"PYTHONPATH=/root/gentoo-installer "
        f"python3 /root/gentoo-installer/main.py --chroot'"
    )
    print(">>> Entering chroot...\n")
    r = subprocess.run(cmd, shell=True)
    if r.returncode != 0:
        print(f"[!!] chroot phase exited with code {r.returncode}")
        sys.exit(r.returncode)


def run_livecd_phase():
    """The full LiveCD-side flow: menu -> format -> mount -> stage3 -> make.conf -> chroot."""
    CONFIG["cpu_cores"] = detect_cpu_cores()
    print(f"\nDetected CPU cores: {CONFIG['cpu_cores']}\n")

    from menu import main_menu
    main_menu()

    phase_format_partitions()
    phase_mount_partitions()
    phase_download_stage3()
    phase_makeconf()
    phase_repos_conf()
    phase_mount_pseudofs()
    phase_enter_chroot()

    # After chroot returns, unmount & reboot
    from finalize import phase_unmount_and_finish
    phase_unmount_and_finish()
