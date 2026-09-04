"""
detector.py - Environment detection: chroot, CPU cores, block devices,
swap partitions, mounted filesystems, partition classification.
"""

import os
import re
import json
import subprocess


def detect_chroot():
    """True if we're inside the chroot (detected via our marker file)."""
    return os.path.exists("/.gentoo_installer_chroot")


def detect_cpu_cores():
    try:
        return os.cpu_count() or 1
    except NotImplementedError:
        return 1


def list_block_devices():
    """Return lsblk output string for display."""
    try:
        r = subprocess.run(
            ["lsblk", "-o", "NAME,SIZE,FSTYPE,TYPE,MOUNTPOINT"],
            capture_output=True, text=True
        )
        return r.stdout or "(lsblk produced no output)"
    except FileNotFoundError:
        return "(lsblk not found)"


def detect_swap_devices():
    """List active swap devices from /proc/swaps."""
    swaps = []
    try:
        with open("/proc/swaps") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2 and parts[0] != "Filename" and parts[1].isdigit():
                    swaps.append(parts[0])
    except OSError:
        pass
    return swaps


def detect_mounted_under(mountpoint):
    """List mountpoints under `mountpoint`, deepest first.
    Uses findmnt --list; falls back to /proc/mounts."""
    mounts = []
    try:
        r = subprocess.run(
            ["findmnt", "-l", "-R", "-o", "TARGET", "-n", mountpoint],
            capture_output=True, text=True
        )
        if r.returncode == 0 and r.stdout:
            mounts = [l.strip() for l in r.stdout.splitlines() if l.strip()]
    except FileNotFoundError:
        pass
    if not mounts:
        try:
            with open("/proc/mounts") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) > 1 and parts[1].startswith(mountpoint):
                        mounts.append(parts[1])
        except OSError:
            pass
    mounts.sort(key=lambda x: -len(x))
    return mounts


# ---------------------------------------------------------------------------
# Partition detection & classification
# ---------------------------------------------------------------------------

def _parse_size(size_str):
    """Parse a human-readable size string ('1G', '512M', '4.9G', …) to bytes."""
    if not size_str:
        return 0
    s = size_str.strip().upper()
    if not s:
        return 0
    units = {'B': 1, 'K': 1024, 'M': 1024**2,
             'G': 1024**3, 'T': 1024**4, 'P': 1024**5}
    for unit, val in units.items():
        if s.endswith(unit):
            try:
                return int(float(s[:-len(unit)]) * val)
            except ValueError:
                return 0
    try:
        return int(float(s))
    except ValueError:
        return 0


def detect_disk_partitions(disk_dev):
    """Detect all partitions on *disk_dev*.

    Returns a list of dicts, each with keys:
        device      -- full device path, e.g. '/dev/sda1'
        name        -- short name, e.g. 'sda1'
        size        -- human-readable size, e.g. '1G'
        size_bytes  -- integer size in bytes (best-effort)
        fstype      -- filesystem type if already formatted, else ''
        part_type   -- partition type name, e.g. 'EFI System'
        mountpoint  -- current mountpoint or ''
    Returns [] on failure.
    """
    if not disk_dev:
        return []

    # ---- preferred: lsblk JSON -----------------------------------------
    try:
        r = subprocess.run(
            ["lsblk", "-J", "-o", "NAME,SIZE,FSTYPE,PARTTYPENAME,TYPE,MOUNTPOINT",
             disk_dev],
            capture_output=True, text=True
        )
        if r.returncode == 0 and r.stdout.strip():
            data = json.loads(r.stdout)
            parts = []
            for disk in data.get("blockdevices", []):
                for child in disk.get("children") or []:
                    if (child.get("type") or "") != "part":
                        continue
                    name = child.get("name", "")
                    size_str = child.get("size") or ""
                    parts.append({
                        "device":      f"/dev/{name}",
                        "name":        name,
                        "size":        size_str,
                        "size_bytes":  _parse_size(size_str),
                        "fstype":      child.get("fstype") or "",
                        "part_type":   child.get("parttypename") or "",
                        "mountpoint":  child.get("mountpoint") or "",
                    })
            if parts:
                return parts
    except (json.JSONDecodeError, FileNotFoundError, OSError):
        pass

    # ---- fallback: lsblk -P (key=value pairs) --------------------------
    try:
        r = subprocess.run(
            ["lsblk", "-P", "-o", "NAME,SIZE,FSTYPE,PARTTYPENAME,TYPE,MOUNTPOINT",
             disk_dev],
            capture_output=True, text=True
        )
        if r.returncode == 0 and r.stdout.strip():
            parts = []
            for line in r.stdout.splitlines():
                fields = dict(re.findall(r'(\w+)="([^"]*)"', line))
                if (fields.get("TYPE") or "") != "part":
                    continue
                name = fields.get("NAME", "")
                size_str = fields.get("SIZE", "")
                parts.append({
                    "device":      f"/dev/{name}",
                    "name":        name,
                    "size":        size_str,
                    "size_bytes":  _parse_size(size_str),
                    "fstype":      fields.get("FSTYPE", ""),
                    "part_type":   fields.get("PARTTYPENAME", ""),
                    "mountpoint":  fields.get("MOUNTPOINT", ""),
                })
            if parts:
                return parts
    except (FileNotFoundError, OSError):
        pass

    # ---- last resort: fdisk -l -----------------------------------------
    try:
        r = subprocess.run(
            ["fdisk", "-l", disk_dev],
            capture_output=True, text=True
        )
        if r.returncode == 0 and r.stdout:
            parts = []
            for line in r.stdout.splitlines():
                m = re.match(
                    r'^(dev/\S+)\s+\*?\s*(\d+)\s+(\d+)\s+(\d+\w?)\s+(.+)$',
                    line.strip()
                )
                if not m:
                    continue
                dev = m.group(1)
                if not dev.startswith("/dev/"):
                    dev = "/dev/" + dev
                size_field = m.group(4)
                rest = m.group(5).strip()
                # try to extract type from the rest of the line
                part_type = ""
                for kw in ("EFI System", "Linux swap", "Linux filesystem",
                           "EFI (FAT-12/16/32)"):
                    if kw.lower() in rest.lower():
                        part_type = kw
                        break
                if not part_type:
                    part_type = rest
                parts.append({
                    "device":      dev,
                    "name":        dev.split("/")[-1],
                    "size":        size_field,
                    "size_bytes":  _parse_size(size_field),
                    "fstype":      "",
                    "part_type":   part_type,
                    "mountpoint":  "",
                })
            if parts:
                return parts
    except (FileNotFoundError, OSError):
        pass

    return []


def classify_partitions(partitions):
    """Classify a list of partition dicts into roles.

    Roles:
        efi   -- EFI System partition  (always vfat / FAT32)
        swap  -- Linux swap partition   (always swap)
        root  -- the largest remaining Linux filesystem partition
        data  -- all other Linux filesystem partitions

    Returns a dict: {"efi": dict|None, "swap": dict|None,
                      "root": dict|None, "data": [dict, …]}
    """
    result = {"efi": None, "swap": None, "root": None, "data": []}

    remaining = []
    for p in partitions:
        pt = (p.get("part_type") or "").lower()
        fs = (p.get("fstype") or "").lower()

        if "efi" in pt or pt == "efi (fat-12/16/32)":
            result["efi"] = p
        elif "swap" in pt or fs == "swap":
            result["swap"] = p
        else:
            remaining.append(p)

    # Root = the largest remaining partition (heuristic)
    if remaining:
        remaining.sort(key=lambda x: x.get("size_bytes", 0), reverse=True)
        result["root"] = remaining[0]
        result["data"] = remaining[1:]

    return result
