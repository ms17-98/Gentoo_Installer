"""
stage3.py - Fetch stage3 variant directories and tarball files from a mirror.

Gentoo mirror layout (2024+):
    .../releases/amd64/autobuilds/
        current-stage3-amd64-openrc/
            stage3-amd64-openrc-<timestamp>.tar.xz
            stage3-amd64-openrc-<timestamp>.tar.xz.DIGESTS
            stage3-amd64-openrc-<timestamp>.tar.xz.asc
            ...
        current-stage3-amd64-systemd/
        ...
"""

import re
import urllib.request
from urllib.parse import urlparse

from config import STAGE3_VARIANTS_PREFERRED


def fetch_stage3_variants(mirror_base):
    """Return list of (variant_dir, label) available on the mirror.

    Handles both relative hrefs (NJU/TUNA: 'current-stage3-amd64-openrc/')
    and absolute hrefs (Aliyun/BFSU: '/gentoo/releases/.../current-stage3-amd64-openrc/').
    """
    base_url = f"{mirror_base}/releases/amd64/autobuilds/"
    print(f"\n  Fetching stage3 variants from:\n    {base_url}")
    try:
        req = urllib.request.Request(
            base_url, headers={"User-Agent": "gentoo-installer/1.0"}
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            html = r.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"[!!] Failed to fetch variant list: {e}")
        return []

    dirs = re.findall(r'href="([^"]*current-stage3-amd64-[^"]+/)"', html)
    seen = set()
    out = []
    for d in dirs:
        name = d.rstrip("/").split("/")[-1]
        if name in seen:
            continue
        seen.add(name)
        label = name.replace("current-stage3-", "")
        out.append((name, label))
    return out


def fetch_stage3_files(mirror_base, variant_dir):
    """Return list of (filename, full_url) for .tar.xz files inside a variant
    directory. Excludes .DIGESTS/.asc/.sha256/.CONTENTS.

    Handles both relative and absolute hrefs."""
    listing_url = f"{mirror_base}/releases/amd64/autobuilds/{variant_dir}/"
    print(f"\n  Fetching stage3 files from:\n    {listing_url}")
    try:
        req = urllib.request.Request(
            listing_url, headers={"User-Agent": "gentoo-installer/1.0"}
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            html = r.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"[!!] Failed to fetch file list: {e}")
        return []

    files = re.findall(r'href="([^"]+\.tar\.xz)"', html)
    seen = set()
    out = []
    for f in files:
        name = f.split("/")[-1]
        if not name.startswith("stage3-"):
            continue
        if not name.endswith(".tar.xz"):
            continue
        if name in seen:
            continue
        seen.add(name)
        # build full URL
        if f.startswith("http"):
            full = f
        elif f.startswith("/"):
            p = urlparse(mirror_base)
            full = f"{p.scheme}://{p.netloc}{f}"
        else:
            full = listing_url + f
        out.append((name, full))
    return out


def sort_variants(variants):
    """Sort variants: preferred ones first (in predefined order), rest alphabetical."""
    def key(item):
        vdir = item[0]
        if vdir in STAGE3_VARIANTS_PREFERRED:
            return (0, STAGE3_VARIANTS_PREFERRED.index(vdir))
        return (1, vdir)
    return sorted(variants, key=key)
