#!/usr/bin/env python3
"""Validate a MikuTV plugin directory and build deterministic plugin.zip + SHA256SUMS.txt."""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

MAX_ARCHIVE_BYTES = 8 * 1024 * 1024
MAX_THEME_BYTES = 64 * 1024
MAX_LOCALE_BYTES = 256 * 1024
MIN_ZIP_TIMESTAMP = 315532800  # 1980-01-01T00:00:00Z

PLUGIN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    r"(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
)
README_RE = re.compile(r"^README(?:\.[^.]+)?\.md$", re.IGNORECASE)
EXCLUDED_TOP_LEVEL = {
    "README.md",
    "CHANGELOG.md",
    "screenshots",
    "docs",
    "plugin.zip",
    "SHA256SUMS.txt",
}
LICENSE_FILES = ("LICENSE", "LICENSE.txt", "NOTICE")


def fail(message: str) -> None:
    print(f"Error: {message}", file=sys.stderr)
    raise SystemExit(1)


def is_excluded(rel: Path) -> bool:
    parts = rel.parts
    if not parts:
        return True
    if any(part.startswith(".") for part in parts):
        return True
    if parts[0] in EXCLUDED_TOP_LEVEL:
        return True
    if len(parts) == 1 and README_RE.fullmatch(parts[0]):
        return True
    return False


def validate_rel_path(rel_posix: str) -> None:
    if "\\" in rel_posix or any(ord(ch) < 32 or ord(ch) == 127 for ch in rel_posix):
        fail(f"invalid archive path: {rel_posix!r}")


def resolve_commit_timestamp(root: Path) -> int:
    try:
        out = subprocess.check_output(
            ["git", "show", "-s", "--format=%ct", "HEAD"],
            cwd=root,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return max(int(out), MIN_ZIP_TIMESTAMP)
    except Exception:
        return MIN_ZIP_TIMESTAMP


def package_plugin(
    root: Path,
    *,
    input_tag: str = "",
    event_name: str = "",
    ref_name: str = "",
    ref_type: str = "",
) -> dict[str, str]:
    manifest_path = root / "plugin.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        fail("plugin.json not found at repository root")

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"plugin.json is not valid JSON: {exc}")

    if not isinstance(manifest, dict):
        fail("plugin.json must be a JSON object")

    for field in ("id", "name", "kind", "version", "license"):
        val = manifest.get(field)
        if not isinstance(val, str) or not val.strip():
            fail(f"plugin.json missing required string field: {field}")

    plugin_id = manifest["id"].strip()
    if not PLUGIN_ID_RE.fullmatch(plugin_id):
        fail(f"invalid plugin id: {plugin_id!r}")

    if manifest.get("apiVersion") != 1:
        fail(f"unsupported apiVersion: {manifest.get('apiVersion')!r}")

    version = manifest["version"].strip()
    semver_match = SEMVER_RE.fullmatch(version)
    if not semver_match:
        fail(f"version must be valid canonical semver, got {version!r}")
    is_prerelease = bool(semver_match.group(4))

    kind = manifest["kind"].strip()
    if kind not in ("source", "theme", "locale"):
        fail(f"unsupported plugin kind: {kind!r}")

    expected_tag = f"v{version}"
    clean_input_tag = input_tag.strip()
    if clean_input_tag:
        target_tag = clean_input_tag
    elif ref_type == "tag" or (event_name == "push" and ref_name.startswith("v")):
        target_tag = ref_name.strip()
    else:
        target_tag = expected_tag

    if target_tag != expected_tag:
        fail(
            f"tag {target_tag!r} does not match plugin.json version {version!r} "
            f"(expected {expected_tag!r})"
        )

    files: list[tuple[str, Path]] = []
    seen_lower: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if is_excluded(rel):
            continue
        if p.is_symlink():
            fail(f"symlinks are not allowed in plugin archives: {rel.as_posix()}")
        if not p.is_file():
            continue
        rel_posix = rel.as_posix()
        validate_rel_path(rel_posix)
        lowered = rel_posix.lower()
        if lowered in seen_lower:
            fail(f"case-insensitive duplicate path: {seen_lower[lowered]!r} vs {rel_posix!r}")
        seen_lower[lowered] = rel_posix
        files.append((rel_posix, p))

    rel_set = {rel for rel, _ in files}
    required = {"plugin.json"}

    if not any(name in rel_set for name in LICENSE_FILES):
        fail(f"missing license file at archive root (expected one of {', '.join(LICENSE_FILES)})")

    if kind == "source":
        main_file = manifest.get("main")
        if not isinstance(main_file, str) or not main_file.strip():
            fail("source plugin.json missing main entrypoint")
        required.add(main_file.strip())
        for nested in (
            (manifest.get("artwork") or {}).get("cover"),
            ((manifest.get("authentication") or {}).get("presentation") or {}).get("guestArtwork"),
        ):
            if isinstance(nested, str) and nested.strip():
                required.add(nested.strip())
    elif kind == "theme":
        theme_file = manifest.get("theme")
        if not isinstance(theme_file, str) or not theme_file.strip():
            theme_file = "theme.json"
        theme_file = theme_file.strip()
        required.add(theme_file)
        theme_path = root / theme_file
        if theme_path.is_file() and not theme_path.is_symlink():
            if theme_path.stat().st_size > MAX_THEME_BYTES:
                fail(f"{theme_file} exceeds 64 KiB limit")
            try:
                json.loads(theme_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                fail(f"{theme_file} is not valid JSON: {exc}")
    elif kind == "locale":
        locale_file = manifest.get("locale")
        if not isinstance(locale_file, str) or not locale_file.strip():
            locale_file = "locale.json"
        locale_file = locale_file.strip()
        required.add(locale_file)
        locale_path = root / locale_file
        if locale_path.is_file() and not locale_path.is_symlink():
            if locale_path.stat().st_size > MAX_LOCALE_BYTES:
                fail(f"{locale_file} exceeds 256 KiB limit")
            try:
                json.loads(locale_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                fail(f"{locale_file} is not valid JSON: {exc}")

    missing = sorted(r for r in required if r not in rel_set)
    if missing:
        fail(f"missing required package files: {missing}")

    ts = resolve_commit_timestamp(root)
    dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
    zip_dt = (dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)

    out_zip = root / "plugin.zip"
    with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for rel, p in files:
            zi = zipfile.ZipInfo(rel, date_time=zip_dt)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            zf.writestr(zi, p.read_bytes())

    raw = out_zip.read_bytes()
    if len(raw) > MAX_ARCHIVE_BYTES:
        out_zip.unlink(missing_ok=True)
        fail(f"plugin.zip size {len(raw)} exceeds 8 MiB limit ({MAX_ARCHIVE_BYTES} bytes)")

    sha = hashlib.sha256(raw).hexdigest()
    checksums_path = root / "SHA256SUMS.txt"
    checksums_path.write_text(f"{sha}  plugin.zip\n", encoding="utf-8")

    print(
        f"Packaged {plugin_id} {version} ({kind}): "
        f"{len(files)} files, {len(raw)} bytes, sha256={sha}, prerelease={str(is_prerelease).lower()}"
    )

    return {
        "tag": target_tag,
        "version": version,
        "plugin-id": plugin_id,
        "kind": kind,
        "sha256": sha,
        "bytes": str(len(raw)),
        "prerelease": "true" if is_prerelease else "false",
        "zip-path": str(out_zip),
        "checksums-path": str(checksums_path),
    }


def main() -> None:
    root = Path(os.environ.get("INPUT_WORKING_DIRECTORY", ".") or ".").resolve()
    outputs = package_plugin(
        root,
        input_tag=os.environ.get("INPUT_TAG", ""),
        event_name=os.environ.get("EVENT_NAME", ""),
        ref_name=os.environ.get("REF_NAME", ""),
        ref_type=os.environ.get("REF_TYPE", ""),
    )

    github_output = os.environ.get("GITHUB_OUTPUT", "").strip()
    if github_output:
        with open(github_output, "a", encoding="utf-8") as fh:
            for key, value in outputs.items():
                fh.write(f"{key}={value}\n")


if __name__ == "__main__":
    main()
