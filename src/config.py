"""
config.py - Global constants and configuration state for the Gentoo installer.
"""

# ===========================================================================
# Mirrors (all verified: list + download OK as of 2025-07)
# ===========================================================================

MIRRORS = [
    ("NJU (Nanjing University)",      "https://mirrors.nju.edu.cn/gentoo"),
    ("Aliyun (Alibaba Cloud)",        "https://mirrors.aliyun.com/gentoo"),
    ("TUNA (Tsinghua)",               "https://mirrors.tuna.tsinghua.edu.cn/gentoo"),
    ("BFSU (Beijing Foreign Studies)","https://mirrors.bfsu.edu.cn/gentoo"),
    ("Huawei Cloud",                  "https://mirrors.huaweicloud.com/gentoo"),
]

# ===========================================================================
# Filesystem options for non-EFI, non-swap partitions
# (label, mkfs_prefix) -- EFI is always vfat, swap is always swap.
# ===========================================================================

FILESYSTEMS = [
    ("ext4 (recommended)",     "ext4"),
    ("btrfs (snapshot support)", "btrfs"),
    ("xfs (high performance)",  "xfs"),
    ("f2fs (flash/SSD)",        "f2fs"),
    ("ext3 (legacy journaling)", "ext3"),
    ("ext2 (no journaling)",    "ext2"),
]

# mkfs command templates keyed by filesystem name
FORMAT_COMMANDS = {
    "vfat":  "mkfs.vfat -F32",
    "ext2":  "mkfs.ext2 -F",
    "ext3":  "mkfs.ext3 -F",
    "ext4":  "mkfs.ext4 -F",
    "btrfs": "mkfs.btrfs -f",
    "xfs":   "mkfs.xfs -f",
    "f2fs":  "mkfs.f2fs -f",
    "swap":  "mkswap",
}

PORTAGE_SYNC = {
    "https://mirrors.nju.edu.cn/gentoo":           "https://mirrors.nju.edu.cn/gentoo-portage",
    "https://mirrors.aliyun.com/gentoo":           "https://mirrors.aliyun.com/gentoo-portage",
    "https://mirrors.tuna.tsinghua.edu.cn/gentoo": "https://mirrors.tuna.tsinghua.edu.cn/gentoo-portage",
    "https://mirrors.bfsu.edu.cn/gentoo":          "https://mirrors.bfsu.edu.cn/gentoo-portage",
    "https://mirrors.huaweicloud.com/gentoo":      "https://mirrors.huaweicloud.com/gentoo-portage",
}

# ===========================================================================
# Desktop environments
# key -> (label, package_atom, display_manager)
# ===========================================================================

DESKTOPS = {
    "none":     ("No desktop (server / CLI only)", "",                               ""),
    "xfce4":    ("XFCE4 (lightweight, GTK)",        "xfce-base/xfce4-meta",           "lxdm"),
    "kde":      ("KDE Plasma (full-featured)",      "kde-plasma/plasma-meta",         "sddm"),
    "gnome":    ("GNOME (modern, Wayland-first)",   "gnome-base/gnome",               "gdm"),
    "cinnamon": ("Cinnamon (traditional, GTK)",     "gnome-extra/cinnamon-meta",      "lxdm"),
    "mate":     ("MATE (classic GNOME2 fork)",      "mate-base/mate",                 "lxdm"),
    "i3":       ("i3wm (tiling, X11)",              "x11-wm/i3",                      "xinit"),
    "bspwm":    ("bspwm (tiling, X11)",             "x11-wm/bspwm",                   "xinit"),
    "hyprland": ("Hyprland (tiling, Wayland)",      "gui-wm/hyprland",                "sddm"),
}

KERNEL_METHODS = [
    ("menuconfig (user-tuned)", "menuconfig"),
    ("defconfig (auto, fastest)", "defconfig"),
]

# Stage3 variant dirs preferred at top of the list
STAGE3_VARIANTS_PREFERRED = [
    "current-stage3-amd64-openrc",
    "current-stage3-amd64-systemd",
    "current-stage3-amd64-desktop-openrc",
    "current-stage3-amd64-desktop-systemd",
    "current-stage3-amd64-musl-openrc",
    "current-stage3-amd64-nomultilib-openrc",
    "current-stage3-amd64-hardened-openrc",
    "current-stage3-amd64-llvm-openrc",
]

# ===========================================================================
# Global configuration - filled by menu, consumed by installer phases
# ===========================================================================

CONFIG = {
    # disk
    "disk_dev":          None,
    "root_part":         None,
    "boot_part":         None,
    "swap_part":         "",
    # partitions list -- filled by menu_disk(), consumed by format/mount phases.
    # Each entry: {"device","role","fstype","mountpoint","size","part_type"}
    "partitions":        [],
    # mirror / stage3
    "mirror":            "https://mirrors.nju.edu.cn/gentoo",
    "mirror_name":       "NJU (Nanjing University)",
    "stage3_url":        None,
    "stage3_file":       None,
    # system
    "timezone":          "Asia/Shanghai",
    "hostname":          "gentoo",
    "username":          "gentoo",
    "desktop":           "none",
    "kernel_method":     "menuconfig",
    # runtime
    "cpu_cores":         1,
    "mountpoint":        "/mnt/gentoo",
    "in_chroot":         False,
}
