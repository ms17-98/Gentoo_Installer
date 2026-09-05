# Gentoo Linux Installer

Pentoo/archinstall-style automated installer for Gentoo Linux.

Interactive menu-driven installer that formats partitions, downloads & extracts
a stage3 tarball, configures Portage, enters a chroot, builds the kernel, sets
up a desktop environment (optional), creates a user, and installs GRUB for UEFI.

OpenRC | UEFI | dracut | multi-desktop

## Project status

This project was paused for several months and has now been restarted. The
current installer has been tested successfully and is intended to make a
Gentoo installation more approachable for beginners without removing the
power and flexibility of Gentoo underneath.

Gentoo is still a source-based distribution: Portage will compile packages
according to the selected profile and USE flags. This project automates the
installation workflow so users do not have to manually perform every step.

## Files

All source lives under `src/`:

| File | Purpose |
|---|---|
| `src/main.py` | Entry point (`--chroot` is auto-invoked inside chroot) |
| `src/config.py` | Mirrors, desktops, kernel methods, global `CONFIG` dict |
| `src/helpers.py` | `run`/`ask`/`confirm`/`choose`/`banner` utilities |
| `src/detector.py` | chroot/CPU/swap/mount detection + partition auto-detect & classify |
| `src/stage3.py` | Mirror stage3 variant & file listing |
| `src/menu.py` | Main menu + sub-menus (archinstall style) + partition/fs selection |
| `src/livecd.py` | LiveCD phase: format, mount, stage3, make.conf, chroot entry |
| `src/chroot_phase.py` | Chroot phase: sync, kernel, desktop, tools, user, grub |
| `src/finalize.py` | umount + reboot/poweroff |
| `tests/test_basic.py` | Pure-logic smoke tests (no root needed) |

## Usage

```bash
# Run directly from a Gentoo LiveCD (root required)
python3 src/main.py

# Unit tests (run anywhere with Python 3)
python3 tests/test_basic.py

# Build a single-file executable with PyInstaller
# (pinned spec in the repo — no flags to remember)
pyinstaller --onefile --add-data 'src/*.py:src' src/main.py
# result: dist/gentoo-installer(.exe)
```

The installer must be run as root from a Gentoo LiveCD or another suitable
Linux rescue environment. It can format partitions and install a complete
system, so verify the selected disk and partition plan before confirming.

> [!IMPORTANT]
> If you bundle with PyInstaller, the `.py` sources **must** be included as
> data files — the pinned `gentoo-installer.spec` already does this via
> `datas=[('src/*.py', 'src')]`. If you instead run `pyinstaller` on
> `src/main.py` directly, pass `--add-data 'src/*.py:src'`, otherwise
> Step 6 (Enter chroot) cannot find `main.py` to copy into the chroot.
>
> Running the one-file bundle unpacks to a temporary `sys._MEIPASS` dir;
> `_find_main_py_source()` looks there as well, so the bundled sources
> are found and copied into the chroot just like in a source checkout.

## Mirrors (all verified)

- NJU (Nanjing University) — default
- Aliyun (Alibaba Cloud)
- TUNA (Tsinghua)
- BFSU (Beijing Foreign Studies)
- Huawei Cloud

## Flow

1. Main menu: configure disk / mirror / stage3 / timezone / hostname / username / desktop / kernel
2. Disk menu auto-detects all partitions on the selected disk and classifies them
   (EFI / swap / root / data) — supports any number of partitions (3, 4, 5, 6+)
3. User picks a filesystem for root/data partitions (ext4/btrfs/xfs/f2fs/ext3/ext2;
   EFI is always vfat, swap is always swapfs)
4. Installer formats every partition with the matching `mkfs` command, then mounts
  them in the correct order (root → data/EFI → swap); the EFI partition is mounted
  at `/boot` so kernel and initramfs files are written to the boot filesystem
5. Confirm → automated install
6. Chroot entry (`phase_enter_chroot`):
   - Creates `<mountpoint>/root/gentoo-installer/`
   - Locates `main.py` via `_find_main_py_source()` — supports both the normal
     `src/` layout, a `<project-root>/main.py` layout, and PyInstaller's
     `sys._MEIPASS` extraction dir
   - Explicitly copies `main.py` first, then all sibling `.py` modules,
     then writes `.installer_config.json`
   - Sanity-checks `main.py` exists at destination before entering
     chroot — fails fast with a clear FATAL message instead of a cryptic
     "No such file" from inside chroot
7. Only interactive prompts: `cfdisk` (optional) and `make menuconfig` (optional)

## Partition handling

- `detect_disk_partitions()` reads the partition table via `lsblk -J` (JSON),
  falling back to `lsblk -P` then `fdisk -l` if needed
- `classify_partitions()` assigns roles automatically:
  `EFI` (PARTTYPENAME contains "EFI") → vfat, `swap` → swap, largest remaining → root,
  everything else → data (user chooses its filesystem)
- Mountpoints are validated against a safe character set before being passed
  to shell commands
- The EFI partition is mounted at `/boot`. Before `make install`, the installer
  verifies that `/boot` is really mounted, preventing kernel files from being
  written accidentally to the root filesystem's `/boot` directory
- `/etc/fstab` is generated inside the chroot: `genfstab -U` (from
  `sys-apps/arch-install-scripts`) when available, otherwise a built-in
  generator that writes the fstab straight from the partition plan, so an
  fstab is always produced even if an earlier emerge step failed

## Reliability notes

- `make.conf` USE flags are derived from the selected desktop (e.g. `kde`
  gets `X qt6 kde`, `gnome` gets `X gtk gnome`); a hardcoded negative USE
  list would silently break the chosen desktop
- With the `defconfig` kernel method, the boot-critical filesystem drivers
  are enabled automatically (`scripts/config` + `make olddefconfig`): the
  root filesystem (incl. btrfs/xfs/f2fs), vfat for `/boot`, and
  EFI/efivarfs for UEFI boot — otherwise a non-ext4 root would fail to mount
  and the machine would not boot
- GRUB uses `/boot` as the EFI directory and refuses to install if it is not
  mounted (asks before continuing), so a missing ESP fails loudly instead of
  silently producing an unbootable system

## Acknowledgements

The design and direction of this project were informed by:

- Pentoo installation scripts
- Archinstall
- Sabayon Linux
- Redcore Linux

These projects provided useful ideas for automating a complex Linux
installation while keeping important choices visible to the user. This
installer is an independent project and is not affiliated with them.

## License

See [LICENSE](LICENSE).
