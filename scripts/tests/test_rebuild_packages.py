#!/usr/bin/env python3
"""
tests/test_rebuild_packages.py
Lancer avec : python3 -m pytest tests/ -v
ou           : python3 tests/test_rebuild_packages.py
"""
import json
import sys
import tarfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open
import tempfile
import shutil

# on ajoute scripts/ au path pour importer rebuild_packages
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import rebuild_packages as rp


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def make_manifest(items: list[dict]) -> dict:
    return {"binaries": items, "libs": [], "configs": []}


# ──────────────────────────────────────────────────────────────────────────────
# parse_semver
# ──────────────────────────────────────────────────────────────────────────────

class TestParseSemver(unittest.TestCase):

    def test_with_v_prefix(self):
        v = rp.parse_semver("v1.2.3")
        self.assertEqual((v.major, v.minor, v.micro), (1, 2, 3))

    def test_without_v_prefix(self):
        v = rp.parse_semver("0.0.14")
        self.assertEqual((v.major, v.minor, v.micro), (0, 0, 14))

    def test_invalid_returns_none(self):
        self.assertIsNone(rp.parse_semver("not-a-version"))
        self.assertIsNone(rp.parse_semver("latest"))


# ──────────────────────────────────────────────────────────────────────────────
# resolve_tag
# ──────────────────────────────────────────────────────────────────────────────

FAKE_TAGS = ["v1.0.0", "v1.2.3", "v1.3.0", "v2.0.0", "v0.9.0"]

class TestResolveTag(unittest.TestCase):

    def _patch_tags(self):
        return patch.object(rp, "get_all_tags", return_value=FAKE_TAGS)

    def test_exact_version(self):
        self.assertEqual(rp.resolve_tag("repo", "v1.2.3", "tok"), "v1.2.3")

    def test_star_returns_latest(self):
        with self._patch_tags():
            result = rp.resolve_tag("repo", "*", "tok")
        self.assertEqual(result, "v2.0.0")

    def test_caret_same_major(self):
        with self._patch_tags():
            result = rp.resolve_tag("repo", "^v1.0.0", "tok")
        self.assertEqual(result, "v1.3.0")

    def test_caret_excludes_higher_major(self):
        with self._patch_tags():
            result = rp.resolve_tag("repo", "^v1.2.0", "tok")
        self.assertNotEqual(result, "v2.0.0")
        self.assertEqual(result, "v1.3.0")

    def test_tilde_same_major_minor(self):
        with self._patch_tags():
            result = rp.resolve_tag("repo", "~v1.2.0", "tok")
        self.assertEqual(result, "v1.2.3")

    def test_tilde_excludes_different_minor(self):
        with self._patch_tags():
            result = rp.resolve_tag("repo", "~v1.2.0", "tok")
        self.assertNotIn(result, ["v1.3.0", "v2.0.0"])

    def test_gte(self):
        with self._patch_tags():
            result = rp.resolve_tag("repo", ">=v1.2.0", "tok")
        self.assertEqual(result, "v2.0.0")

    def test_no_candidate_raises(self):
        with self._patch_tags():
            with self.assertRaises(SystemExit):
                rp.resolve_tag("repo", "^v9.0.0", "tok")

    def test_unsupported_spec_raises(self):
        with self._patch_tags():
            with self.assertRaises(SystemExit):
                rp.resolve_tag("repo", "<=v1.0.0", "tok")


# ──────────────────────────────────────────────────────────────────────────────
# resolve_version_for_item
# ──────────────────────────────────────────────────────────────────────────────

class TestResolveVersionForItem(unittest.TestCase):

    def _item(self, repo, version):
        return {"repo": repo, "version": version, "asset": "{tag}.tar.gz", "path": f"artifacts/{repo}/bin"}

    def test_trigger_repo_star(self):
        item = self._item("repo-bin2", "*")
        result = rp.resolve_version_for_item(item, "repo-bin2", "v0.0.24", "tok")
        self.assertEqual(result, "v0.0.24")

    def test_trigger_repo_exact_match(self):
        item = self._item("repo-bin2", "v0.0.24")
        result = rp.resolve_version_for_item(item, "repo-bin2", "v0.0.24", "tok")
        self.assertEqual(result, "v0.0.24")

    def test_trigger_repo_exact_mismatch_raises(self):
        item = self._item("repo-bin2", "v0.0.10")
        with self.assertRaises(SystemExit):
            rp.resolve_version_for_item(item, "repo-bin2", "v0.0.24", "tok")

    def test_trigger_repo_caret_ok(self):
        item = self._item("repo-bin2", "^v0.0.1")
        result = rp.resolve_version_for_item(item, "repo-bin2", "v0.0.24", "tok")
        self.assertEqual(result, "v0.0.24")

    def test_trigger_repo_caret_wrong_major_raises(self):
        item = self._item("repo-bin2", "^v1.0.0")
        with self.assertRaises(SystemExit):
            rp.resolve_version_for_item(item, "repo-bin2", "v0.0.24", "tok")

    def test_other_repo_delegates_to_resolve_tag(self):
        item = self._item("repo-lib1", "^v1.0.0")
        with patch.object(rp, "resolve_tag", return_value="v1.2.3") as mock_rt:
            result = rp.resolve_version_for_item(item, "repo-bin2", "v0.0.24", "tok")
        mock_rt.assert_called_once_with("repo-lib1", "^v1.0.0", "tok")
        self.assertEqual(result, "v1.2.3")


# ──────────────────────────────────────────────────────────────────────────────
# manifest_uses_repo
# ──────────────────────────────────────────────────────────────────────────────

class TestManifestUsesRepo(unittest.TestCase):

    def _write_manifest(self, path: Path, items: list[dict]):
        path.write_text(json.dumps(make_manifest(items)), encoding="utf-8")

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_repo_present(self):
        p = self.tmp / "manifest.json"
        self._write_manifest(p, [{"repo": "repo-bin2", "version": "*", "asset": "x.tar.gz", "path": "a/b"}])
        self.assertTrue(rp.manifest_uses_repo(p, "repo-bin2"))

    def test_repo_absent(self):
        p = self.tmp / "manifest.json"
        self._write_manifest(p, [{"repo": "repo-lib1", "version": "*", "asset": "x.tar.gz", "path": "a/b"}])
        self.assertFalse(rp.manifest_uses_repo(p, "repo-bin2"))

    def test_empty_manifest(self):
        p = self.tmp / "manifest.json"
        p.write_text(json.dumps({"binaries": [], "libs": [], "configs": []}))
        self.assertFalse(rp.manifest_uses_repo(p, "repo-bin2"))


# ──────────────────────────────────────────────────────────────────────────────
# download_asset (mock réseau)
# ──────────────────────────────────────────────────────────────────────────────

class TestDownloadAsset(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _make_fake_tar(self) -> bytes:
        import io
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            content = b"fake binary content"
            info = tarfile.TarInfo(name="binary_two")
            info.size = len(content)
            tf.addfile(info, io.BytesIO(content))
        return buf.getvalue()

    def test_downloads_and_extracts(self):
        fake_tar = self._make_fake_tar()
        mock_resp = MagicMock()
        mock_resp.read.return_value = fake_tar
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            rp.download_asset("repo-bin2", "v0.0.24", "binary_two-v0.0.24.tar.gz", self.tmp, "tok")

        self.assertTrue((self.tmp / "binary_two-v0.0.24.tar.gz").exists())
        self.assertTrue((self.tmp / "binary_two").exists())

    def test_http_error_raises(self):
        import urllib.error
        with patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError(None, 404, "Not Found", {}, None)):
            with self.assertRaises(SystemExit):
                rp.download_asset("repo-bin2", "v9.9.9", "missing.tar.gz", self.tmp, "tok")


# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main(verbosity=2)