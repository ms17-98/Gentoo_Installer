"""
chroot_phase.py - Runs inside the chroot: sync Portage, build kernel,
install desktop/tools/user/grub.
"""

import glob
import os
import re
import sys
import json
import subprocess
from pathlib import Path

from config import CONFIG, DESKTOPS
from helpers import run, run_interactive, pause, banner, confirm
from detector import detect_cpu_cores


def chroot_load_config():
    """Load the config JSON written by the livecd side."""
    # try a few candidate paths
    for p in ("/root/gentoo-installer/.installer_config.json",
              "/root/.installer_config.json"):
        if os.path.exists(p):
            loaded = json.loads(Path(p).read_text())
            CONFIG.update(loaded)
            return
    print("[!] No installer config JSON found; using defaults.")
    CONFIG["cpu_cores"] = detect_cpu_cores()


def chroot_setup_env():
    banner("Chroot: setting up environment")
    os.environ["PATH"] = "/usr/sbin:/usr/bin:/sbin:/bin"
    os.environ["HOME"] = "/root"
    if "TERM" not in os.environ:
        os.environ["TERM"] = "linux"
    print("[OK] Environment ready (PATH/HOME/TERM set).")


def chroot_fix_repos():
    """Fix repos.conf so emerge-webrsync can run.

    Stage3 tarballs sometimes ship repos.conf with sync-type=git.
    emerge-webrsync strictly requires sync-type to be 'rsync' or 'webrsync'.
    We write a minimal override to /etc/portage/repos.conf/gentoo.conf so
    the initial tree population works; sync-type is restored to git after
    dev-vcs/git is installed.
    """
    repo_dir = "/var/db/repos/gentoo"
    os.makedirs(repo_dir, exist_ok=True)

    repos_conf_dir = "/etc/portage/repos.conf"
    os.makedirs(repos_conf_dir, exist_ok=True)

    gentoo_conf = os.path.join(repos_conf_dir, "gentoo.conf")

    # If a gentoo.conf already exists and doesn't use git, leave it alone.
    if os.path.exists(gentoo_conf):
        txt = Path(gentoo_conf).read_text()
        if "sync-type" in txt and "git" not in txt.lower():
            print(f"[OK] {gentoo_conf} already non-git")
            return

    content = f"""[gentoo]
location = {repo_dir}
sync-type = rsync
sync-uri = rsync://rsync.gentoo.org/gentoo-portage
auto-sync = yes
"""
    Path(gentoo_conf).write_text(content)
    print(f"[OK] Wrote {gentoo_conf} with sync-type=rsync for initial webrsync")


def _restore_git_sync_type():
    """After git is installed, restore sync-type=git if we temporarily
    switched it to rsync in chroot_fix_repos()."""
    gentoo_conf = "/etc/portage/repos.conf/gentoo.conf"
    if not os.path.exists(gentoo_conf):
        return
    txt = Path(gentoo_conf).read_text()
    if "sync-type = rsync" in txt:
        txt = txt.replace("sync-type = rsync", "sync-type = git")
        Path(gentoo_conf).write_text(txt)
        print("[OK] Restored repos.conf sync-type to git")


def chroot_sync():
    banner("Chroot: sync Portage tree")
    # repos.conf was fixed by chroot_fix_repos() to use rsync so that
    # emerge-webrsync can populate the tree without git being present.
    r = run("emerge-webrsync", check=False)
    if r.returncode != 0:
        print("[!!] emerge-webrsync failed — Portage tree may be incomplete.")
        print("     Check network connectivity and mirror status.")

    r = run("command -v git", check=False, capture=True)
    if r.returncode != 0:
        print("  git not found; emerging dev-vcs/git ...")
        run("emerge -v dev-vcs/git", check=False)

    # Restore git sync-type now that git is available.
    _restore_git_sync_type()

    run("emerge --sync", check=False)
    run("eselect news list", check=False, capture=True)


def chroot_fix_profile():
    """Ensure /etc/portage/make.profile is a valid symlink.

    Stage3 tarballs occasionally ship make.profile as a plain file or
    hard link instead of a symlink.  Portage refuses to work when this
    happens, so we detect it and recreate the symlink before any emerge
    step that needs a valid profile.
    """
    profile_link = "/etc/portage/make.profile"
    if os.path.islink(profile_link):
        target = os.readlink(profile_link)
        abs_target = os.path.join(os.path.dirname(profile_link), target)
        if os.path.exists(abs_target):
            print(f"[OK] Profile symlink valid: {target}")
            return
        print(f"[!] Profile symlink target missing: {target}")

    print(f"[!] {profile_link} is not a valid symlink — attempting to fix")

    # If it's a plain file, read the intended target path from it.
    if os.path.isfile(profile_link) and not os.path.islink(profile_link):
        try:
            target = Path(profile_link).read_text().strip()
            if target and not target.startswith('#'):
                print(f"    Recreating as symlink -> {target}")
                os.remove(profile_link)
                os.symlink(target, profile_link)
                return
        except Exception as e:
            print(f"    Failed to read profile file: {e}")

    # Fall back: find a default profile in the Portage tree.
    repo_profiles = "/var/db/repos/gentoo/profiles"
    if os.path.isdir(repo_profiles):
        candidates = sorted(glob.glob(f"{repo_profiles}/default/linux/amd64/*"))
        for c in candidates:
            if os.path.isdir(c):
                rel = os.path.relpath(c, os.path.dirname(profile_link))
                print(f"    Setting profile to {rel}")
                if os.path.exists(profile_link):
                    os.remove(profile_link)
                os.symlink(rel, profile_link)
                return

    print(f"[!!] Cannot fix {profile_link}.")
    print(f"     The Portage tree at {repo_profiles} is missing or empty.")
    print(f"     Make sure 'emerge-webrsync' succeeded before reaching this step.")
    sys.exit(1)


def chroot_profile_world():
    banner("Chroot: profile & @world update")
    run("eselect profile list", check=False)
    print("\nUpdating @world (this may take a long time)...")
    run("emerge -vuDN @world", check=False)


def chroot_timezone_locale():
    banner("Chroot: timezone & locale")
    tz = CONFIG["timezone"]
    tz_path = f"/usr/share/zoneinfo/{tz}"
    if os.path.exists(tz_path):
        run(f"ln -sf {tz_path} /etc/localtime")
        run("hwclock --systohc", check=False)
        Path("/etc/timezone").write_text(tz + "\n")
        print(f"[OK] Timezone = {tz}")
    else:
        print(f"[!] Timezone {tz} not found; skipping.")

    lg = "/etc/locale.gen"
    txt = Path(lg).read_text() if os.path.exists(lg) else ""
    for loc in ("en_US.UTF-8 UTF-8", "zh_CN.UTF-8 UTF-8"):
        txt = re.sub(r'^#\s*' + re.escape(loc), loc, txt, flags=re.MULTILINE)
        if loc not in txt:
            txt += loc + "\n"
    Path(lg).write_text(txt)
    run("locale-gen", check=False)
    run("eselect locale set en_US.utf8", check=False)
    print("[OK] Locale = en_US.utf8")


def chroot_hostname():
    banner("Chroot: hostname")
    hn = CONFIG["hostname"]
    Path("/etc/hostname").write_text(hn + "\n")
    hosts = "/etc/hosts"
    txt = Path(hosts).read_text() if os.path.exists(hosts) else ""
    if "127.0.0.1" not in txt:
        txt = f"127.0.0.1\t{hn}.localhost {hn} localhost\n::1\t\tlocalhost\n" + txt
    else:
        txt = re.sub(r'^(127\.0\.0\.1\s+)', r'\1' + hn + ' ', txt,
                     count=1, flags=re.MULTILINE)
    Path(hosts).write_text(txt)
    print(f"[OK] Hostname = {hn}")


def _build_fstab_text():
    """Build a minimal /etc/fstab from the configured partition plan.

    Uses UUIDs (via blkid) when available, falling back to device paths.
    This keeps the installer independent of external helpers like
    arch-install-scripts' genfstab, so an fstab always gets written even if
    some earlier emerge step failed.
    """
    lines = ["# /etc/fstab generated by gentoo-installer", ""]
    for p in CONFIG.get("partitions", []):
        dev  = p["device"]
        role = p.get("role")
        fs   = p.get("fstype")
        if role == "swap":
            lines.append(f"{dev}\tnone\tswap\tsw\t0 0")
            continue
        mnt = p.get("mountpoint")
        if not mnt:
            continue
        r = run(f"blkid -s UUID -o value {dev}", check=False, capture=True)
        uuid = r.stdout.strip() if r.returncode == 0 else ""
        src = f"UUID={uuid}" if uuid else dev
        opts = "defaults"
        if fs == "vfat":
            opts = "defaults,noatime,fmask=0022,dmask=0022"
        lines.append(f"{src}\t{mnt}\t{fs}\t{opts}\t0 2")
    lines.append("")
    return "\n".join(lines)


def chroot_fstab():
    banner("Chroot: generate /etc/fstab")
    # Prefer genfstab (from sys-apps/arch-install-scripts) when available --
    # it also records btrfs subvolumes etc. -- otherwise fall back to our
    # own generator built from the partition plan in CONFIG.
    r = run("command -v genfstab", check=False, capture=True)
    if r.returncode == 0:
        if os.path.exists("/etc/fstab"):
            run("cp /etc/fstab /etc/fstab.bak", check=False)
        else:
            Path("/etc/fstab").write_text("")
        run("genfstab -U / >> /etc/fstab", check=False)
    else:
        print("  genfstab not found; generating fstab from partition plan.")
        Path("/etc/fstab").write_text(_build_fstab_text())
    print("\n--- /etc/fstab ---")
    print(Path("/etc/fstab").read_text())
    print("--- end ---")


def _enable_boot_essential_config(src):
    """After 'make defconfig', enable the drivers required to actually boot.

    'make defconfig' produces a minimal kernel that by default has NO driver
    for btrfs/xfs/f2fs (and no vfat), so a non-ext4 root filesystem would
    fail to mount and the system would not boot.  We enable:

      - the root filesystem driver   (as a module, so dracut can ship it
                                      in the initramfs)
      - vfat                          (for /boot after first boot)
      - efivarfs + EFI               (required for UEFI boot / NVRAM vars)
    """
    root_fs = "ext4"
    for p in CONFIG.get("partitions", []):
        if p.get("role") == "root":
            root_fs = p.get("fstype", "ext4")
            break

    # ext2/ext3 are served by the ext4 driver on modern kernels.
    sym_for_fs = {
        "ext2":   "CONFIG_EXT4_FS",
        "ext3":   "CONFIG_EXT4_FS",
        "ext4":   "CONFIG_EXT4_FS",
        "btrfs":  "CONFIG_BTRFS_FS",
        "xfs":    "CONFIG_XFS_FS",
        "f2fs":   "CONFIG_F2FS_FS",
    }
    as_module = {"CONFIG_VFAT_FS"}          # /boot (grub reads the ESP itself)
    root_sym = sym_for_fs.get(root_fs)
    if root_sym:
        as_module.add(root_sym)
        # btrfs metadata/data may be zstd/lzo/zlib compressed.
        if root_fs == "btrfs":
            as_module.update([
                "CONFIG_BTRFS_FS_ZSTD",
                "CONFIG_BTRFS_FS_LZO",
                "CONFIG_BTRFS_FS_ZLIB",
            ])
    as_builtin = {"CONFIG_EFI", "CONFIG_EFIVAR_FS"}

    cfg = os.path.join(src, "scripts", "config")
    if not os.path.isfile(cfg):
        print(f"[!] {cfg} not found; cannot tweak kernel config for root={root_fs}.")
        return

    for sym in sorted(as_module):
        run(f"{cfg} -m {sym}", cwd=src)
    for sym in sorted(as_builtin):
        run(f"{cfg} -e {sym}", cwd=src)
    run("make olddefconfig", cwd=src)
    print(f"[OK] Kernel config: enabled {', '.join(sorted(as_module | as_builtin))} "
          f"(root={root_fs})")


def chroot_kernel():
    banner("Chroot: kernel - sources, config, build, initramfs")
    run("emerge sys-kernel/gentoo-sources sys-kernel/linux-firmware sys-kernel/dracut sys-kernel/installkernel",
        check=False)
    run("eselect kernel list", check=False)
    run("eselect kernel set 1", check=False)

    src = "/usr/src/linux"
    if not os.path.exists(src):
        print("[!!] /usr/src/linux missing after emerge.")
        sys.exit(1)

    if CONFIG["kernel_method"] == "defconfig":
        print(f"\nUsing 'make defconfig' at {src}")
        run("make defconfig", cwd=src)
        _enable_boot_essential_config(src)
    else:
        print(f"\nLaunching 'make menuconfig' at {src}")
        print("  Configure your kernel, then Save & Exit to continue.")
        pause("  Press Enter to launch menuconfig...")
        run_interactive("make menuconfig", cwd=src)

    n = CONFIG["cpu_cores"]
    print(f"\nBuilding kernel: make -j{n} ...")
    run(f"make -j{n}", cwd=src)
    print("\nInstalling modules...")
    run("make modules_install", cwd=src)
    if not os.path.ismount("/boot"):
        print("[!!] /boot is not mounted; refusing to install the kernel there.")
        print("     Mount the EFI/boot partition at /boot and run the kernel phase again.")
        sys.exit(1)
    print("\nInstalling kernel image...")
    run("make install", cwd=src)

    # Determine kernel version robustly
    r = subprocess.run("make kernelversion", shell=True, cwd=src,
                       capture_output=True, text=True)
    lines = [l.strip() for l in r.stdout.splitlines() if l.strip()]
    kver = lines[-1] if lines else ""
    if not kver:
        try:
            mods = sorted(os.listdir("/lib/modules"))
            if mods:
                kver = mods[-1]
        except OSError:
            pass
    print(f"\nKernel version: {kver}")

    if kver:
        out_img = f"/boot/initramfs-{kver}.img"
        print(f"\nGenerating initramfs: dracut {out_img} {kver}")
        run(f"dracut --force {out_img} {kver}", check=False)
        print(f"[OK] initramfs -> {out_img}")
    else:
        print("[!] Could not determine kernel version; run dracut manually.")


def chroot_desktop():
    banner("Chroot: desktop environment")
    dv = CONFIG["desktop"]
    if dv == "none" or dv not in DESKTOPS:
        print("[OK] No desktop selected.")
        return
    desc, pkg, dm = DESKTOPS[dv]
    print(f"Installing {desc}")
    print(f"  package: {pkg}")
    print(f"  display manager: {dm}")
    run(f"emerge -v {pkg}", check=False)

    if dm and dm != "xinit":
        dm_pkg = {
            "sddm": "x11-misc/sddm",
            "lxdm": "lxde-base/lxdm",
            "gdm":  "gnome-base/gdm",
        }.get(dm)
        if dm_pkg:
            print(f"\nInstalling display manager: {dm_pkg}")
            run(f"emerge -v {dm_pkg}", check=False)
            # NOTE: no `rc-service ... start` here -- we are inside the chroot,
            # there is no display/dbus yet.  Enable for the default runlevel;
            # it will start on first boot.
            run(f"rc-update add {dm} default", check=False)
            print(f"[OK] {dm} enabled (default runlevel).")
    elif dm == "xinit":
        print("\nInstalling Xorg + xinit (use startx)...")
        run("emerge -v x11-base/xorg-server x11-apps/xinit", check=False)

    term = "kde-apps/konsole" if dv == "kde" else "x11-terms/xterm"
    run(f"emerge -v {term}", check=False)
    print(f"[OK] Desktop '{dv}' installed.")


def chroot_network():
    banner("Chroot: networking (NetworkManager)")
    run("emerge net-misc/networkmanager", check=False)
    run('echo ">=net-wireless/wpa_supplicant-2.11-r4 dbus" >> /etc/portage/package.use/networkmanager', check=False)
    run("rc-service NetworkManager start", check=False)
    run("rc-update add NetworkManager default", check=False)
    print("[OK] NetworkManager enabled.")


def chroot_tools():
    banner("Chroot: system tools")
    # sysklogd
    run("emerge -v app-admin/sysklogd", check=False)
    run("rc-service sysklogd start", check=False)
    run("rc-update add sysklogd default", check=False)
    # cronie
    run("emerge -v sys-process/cronie", check=False)
    run("rc-service cronie start", check=False)
    run("rc-update add cronie default", check=False)
    # bash-completion
    run("emerge -v app-shells/bash-completion", check=False)
    # chrony (service = chronyd)
    run("emerge -v net-misc/chrony", check=False)
    run("rc-service chronyd start", check=False)
    run("rc-update add chronyd default", check=False)
    # sudo
    run("emerge -v app-admin/sudo", check=False)
    print("[OK] System tools installed.")


def chroot_user():
    banner("Chroot: user account & passwords")
    username = CONFIG["username"]
    # NOTE: only standard Gentoo groups -- 'plugdev' etc. do NOT exist by
    # default and would make useradd fail (account silently not created).
    run(f"useradd -m -G users,wheel,audio,video,usb {username}", check=False)
    r = run(f"id {username}", check=False, capture=True)
    if r.returncode != 0:
        print(f"[!] useradd seems to have failed for '{username}'.")
    print(f"\nSet password for {username}:")
    run_interactive(f"passwd {username}")
    print("\nSet password for root:")
    run_interactive("passwd root")

    sudoers = "/etc/sudoers"
    if os.path.exists(sudoers):
        txt = Path(sudoers).read_text()
        new = re.sub(r'^#\s*(%wheel\s+ALL=\(ALL:ALL\)\s+ALL)', r'\1',
                     txt, flags=re.MULTILINE)
        if new == txt:
            new = re.sub(r'^#\s*(%wheel\s+ALL=\(ALL\)\s+ALL)', r'\1',
                         txt, flags=re.MULTILINE)
        Path(sudoers).write_text(new)
        print("[OK] %wheel sudo rule uncommented.")


def chroot_grub():
    banner("Chroot: GRUB bootloader (UEFI)")
    efi_dir = "/boot"
    if not os.path.ismount(efi_dir):
        print(f"[!!] EFI System Partition is NOT mounted at {efi_dir}.")
        print(f"    UEFI boot requires the ESP mounted there; grub-install")
        print(f"    will likely FAIL and the system will not boot.")
        if not confirm("Continue anyway?", default_yes=False):
            print("  Skipping GRUB installation.")
            return
    run("emerge sys-boot/grub:2", check=False)
    run(f"grub-install --target=x86_64-efi --efi-directory={efi_dir}", check=False)
    run("grub-mkconfig -o /boot/grub/grub.cfg", check=False)
    print("[OK] GRUB installed.")


def chroot_finalize():
    banner("Chroot: cleanup")
    try:
        os.remove("/.gentoo_installer_chroot")
    except OSError:
        pass
    print("[OK] Chroot phase complete.")


def run_chroot_phase():
    """The chroot-side flow: load config -> sync -> install everything -> done."""
    chroot_load_config()
    chroot_setup_env()
    chroot_fix_repos()
    chroot_sync()
    chroot_fix_profile()
    chroot_profile_world()
    chroot_timezone_locale()
    chroot_hostname()
    chroot_fstab()
    chroot_kernel()         # may launch make menuconfig
    chroot_desktop()
    chroot_network()
    chroot_tools()
    chroot_user()           # passwd prompts (interactive)
    chroot_grub()
    chroot_finalize()
