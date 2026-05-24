#!/usr/bin/env python3
"""Download Twemoji from npm and install local JS + SVG assets."""

import io
import json
import tarfile
import urllib.request
import urllib.error
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_JS = REPO_ROOT / "core" / "static" / "js"
STATIC_VENDOR = REPO_ROOT / "core" / "static" / "vendor" / "twemoji"
TARGET_JS = STATIC_JS / "twemoji.min.js"
TARGET_SVG = STATIC_VENDOR / "svg"
NPM_REGISTRY = "https://registry.npmjs.org/twemoji"
USER_AGENT = "python-twemoji-fetch/1.0"


def fetch_json(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def download_tarball(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def extract_twemoji_files(tarball_bytes):
    with tarfile.open(fileobj=io.BytesIO(tarball_bytes), mode="r:gz") as tar:
        js_member = None
        svg_members = []

        for member in tar.getmembers():
            if member.isdir():
                continue
            if member.name.endswith("twemoji.min.js"):
                js_member = member
            if (member.name.startswith("package/svg/") or member.name.startswith("package/assets/svg/")) and member.name.endswith(".svg"):
                svg_members.append(member)

        if js_member is None:
            raise RuntimeError("twemoji.min.js was not found in the npm package tarball.")

        STATIC_JS.mkdir(parents=True, exist_ok=True)
        TARGET_SVG.mkdir(parents=True, exist_ok=True)

        with tar.extractfile(js_member) as source, TARGET_JS.open("wb") as out_file:
            out_file.write(source.read())

        if not svg_members:
            raise RuntimeError("No SVG assets were found in the Twemoji package tarball.")

        for member in svg_members:
            if member.name.startswith("package/svg/"):
                rel_path = Path(member.name).relative_to("package/svg")
            else:
                rel_path = Path(member.name).relative_to("package/assets/svg")
            out_path = TARGET_SVG / rel_path
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(member) as source, out_path.open("wb") as out_file:
                out_file.write(source.read())

        return len(svg_members)


def main():
    print("Fetching Twemoji metadata from npm...")
    metadata = fetch_json(NPM_REGISTRY)
    latest = metadata.get("dist-tags", {}).get("latest")
    if not latest:
        raise RuntimeError("Unable to determine the latest Twemoji version from npm metadata.")

    tarball_url = metadata["versions"][latest]["dist"]["tarball"]
    print(f"Downloading Twemoji {latest} from: {tarball_url}")
    tarball_bytes = download_tarball(tarball_url)
    svg_count = extract_twemoji_files(tarball_bytes)
    print(f"Installed local Twemoji JS and {svg_count} SVG assets.")
    return True


if __name__ == "__main__":
    try:
        success = main()
    except urllib.error.URLError as exc:
        print(f"Network error while fetching Twemoji: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    if success:
        try:
            Path(__file__).unlink()
            print("Removed helper script after successful Twemoji installation.")
        except Exception as exc:
            print(f"WARNING: unable to remove helper script: {exc}", file=sys.stderr)
    sys.exit(0)
