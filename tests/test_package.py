import hashlib
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import package  # noqa: E402


class PackagePluginTest(unittest.TestCase):
    def make_repo(self, td: str, manifest: dict, extra_files: dict[str, str]) -> Path:
        root = Path(td)
        (root / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
        for rel, content in extra_files.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        return root

    def test_source_plugin_deterministic_and_excludes_non_runtime_files(self):
        with tempfile.TemporaryDirectory() as td:
            root = self.make_repo(
                td,
                {
                    "id": "example-source",
                    "name": "Example",
                    "kind": "source",
                    "version": "1.2.3",
                    "apiVersion": 1,
                    "license": "Apache-2.0",
                    "main": "index.js",
                },
                {
                    "LICENSE": "Apache-2.0",
                    "index.js": "export function browse() { return {}; }\n",
                    "README.md": "# ignored\n",
                    "README.zh-CN.md": "# ignored\n",
                    "CHANGELOG.md": "# ignored\n",
                    "docs/note.md": "ignored\n",
                    "screenshots/home.png": "ignored",
                    ".github/workflows/release.yml": "ignored",
                },
            )
            out1 = package.package_plugin(root, event_name="push", ref_name="v1.2.3", ref_type="tag")
            sha1 = out1["sha256"]
            self.assertEqual(out1["tag"], "v1.2.3")
            self.assertEqual(out1["prerelease"], "false")
            self.assertEqual(
                (root / "SHA256SUMS.txt").read_text(encoding="utf-8"),
                f"{sha1}  plugin.zip\n",
            )
            with zipfile.ZipFile(root / "plugin.zip") as zf:
                self.assertEqual(zf.namelist(), ["LICENSE", "index.js", "plugin.json"])

            out2 = package.package_plugin(root, event_name="push", ref_name="v1.2.3", ref_type="tag")
            self.assertEqual(sha1, out2["sha256"])
            self.assertEqual(sha1, hashlib.sha256((root / "plugin.zip").read_bytes()).hexdigest())

    def test_theme_and_locale_plugins(self):
        with tempfile.TemporaryDirectory() as td:
            root = self.make_repo(
                td,
                {
                    "id": "demo-theme",
                    "name": "Demo Theme",
                    "kind": "theme",
                    "version": "1.0.0",
                    "apiVersion": 1,
                    "license": "Apache-2.0",
                    "theme": "theme.json",
                },
                {
                    "LICENSE": "Apache-2.0",
                    "theme.json": json.dumps({"schemaVersion": 1, "base": "mikutv-dark"}),
                },
            )
            out = package.package_plugin(root)
            self.assertEqual(out["kind"], "theme")
            self.assertEqual(out["tag"], "v1.0.0")

        with tempfile.TemporaryDirectory() as td:
            root = self.make_repo(
                td,
                {
                    "id": "demo-locale",
                    "name": "Demo Locale",
                    "kind": "locale",
                    "version": "1.0.0",
                    "apiVersion": 1,
                    "license": "Apache-2.0",
                    "locale": "locale.json",
                },
                {
                    "NOTICE": "Notice text",
                    "locale.json": json.dumps({"home": "Home"}),
                },
            )
            out = package.package_plugin(root)
            self.assertEqual(out["kind"], "locale")

    def test_prerelease_detection_vs_build_metadata(self):
        with tempfile.TemporaryDirectory() as td:
            root = self.make_repo(
                td,
                {
                    "id": "demo-pre",
                    "name": "Demo",
                    "kind": "theme",
                    "version": "2.0.0-beta.1+build.4",
                    "apiVersion": 1,
                    "license": "Apache-2.0",
                },
                {"LICENSE": "MIT", "theme.json": "{}"},
            )
            out = package.package_plugin(root, event_name="push", ref_name="v2.0.0-beta.1+build.4", ref_type="tag")
            self.assertEqual(out["prerelease"], "true")

        with tempfile.TemporaryDirectory() as td:
            root = self.make_repo(
                td,
                {
                    "id": "demo-build",
                    "name": "Demo",
                    "kind": "theme",
                    "version": "2.0.0+build-1",
                    "apiVersion": 1,
                    "license": "Apache-2.0",
                },
                {"LICENSE": "MIT", "theme.json": "{}"},
            )
            out = package.package_plugin(root, event_name="push", ref_name="v2.0.0+build-1", ref_type="tag")
            self.assertEqual(out["prerelease"], "false")

    def test_rejects_tag_mismatch_and_symlinks_and_oversize_theme(self):
        with tempfile.TemporaryDirectory() as td:
            root = self.make_repo(
                td,
                {
                    "id": "bad-tag",
                    "name": "Bad",
                    "kind": "theme",
                    "version": "1.0.0",
                    "apiVersion": 1,
                    "license": "Apache-2.0",
                },
                {"LICENSE": "MIT", "theme.json": "{}"},
            )
            with self.assertRaises(SystemExit):
                package.package_plugin(root, event_name="push", ref_name="v1.0.1", ref_type="tag")

        with tempfile.TemporaryDirectory() as td:
            root = self.make_repo(
                td,
                {
                    "id": "bad-link",
                    "name": "Bad",
                    "kind": "theme",
                    "version": "1.0.0",
                    "apiVersion": 1,
                    "license": "Apache-2.0",
                },
                {"LICENSE": "MIT", "theme.json": "{}"},
            )
            os.symlink(root / "LICENSE", root / "link.txt")
            with self.assertRaises(SystemExit):
                package.package_plugin(root)

        with tempfile.TemporaryDirectory() as td:
            root = self.make_repo(
                td,
                {
                    "id": "big-theme",
                    "name": "Big",
                    "kind": "theme",
                    "version": "1.0.0",
                    "apiVersion": 1,
                    "license": "Apache-2.0",
                },
                {"LICENSE": "MIT", "theme.json": json.dumps({"pad": "a" * (65 * 1024)})},
            )
            with self.assertRaises(SystemExit):
                package.package_plugin(root)


if __name__ == "__main__":
    unittest.main()
