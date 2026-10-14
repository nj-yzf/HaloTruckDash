import hashlib
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock
from urllib.error import URLError
from urllib.request import Request
import zipfile

from halo_dashboard.updates import (FORMAT, MAX_MANIFEST, MAX_PACKAGE, HTTPSRedirectHandler,
    Release, UpdateCancelled, download_release, fetch_release, https_url, parse_manifest,
    validate_package, version_tuple)


def package_bytes(extra=None):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as package:
        package.writestr('HaloTruckDash.exe', b'MZ test executable')
        package.writestr('README.md', 'test')
        if extra:
            package.writestr(extra, 'test')
    return output.getvalue()


def manifest(content=None, version='0.6.0'):
    content = content if content is not None else package_bytes()
    return {'format': FORMAT, 'schema': 1, 'version': version, 'notes': '测试更新说明',
            'windows_x64': {'url': 'HaloTruckDash-v0.6.0.zip', 'size': len(content),
                            'sha256': hashlib.sha256(content).hexdigest()}}


class Response(io.BytesIO):
    def __init__(self, content, url='https://updates.invalid/releases/v0.6.0/latest.json', headers=None):
        super().__init__(content)
        self.url, self.headers = url, headers or {}
    def geturl(self):
        return self.url


class UpdateTests(unittest.TestCase):
    def test_numeric_versions_and_no_downgrade_or_prerelease(self):
        self.assertGreater(version_tuple('0.10.0'), version_tuple('0.9.99'))
        self.assertEqual(version_tuple('v1.0.0'), (1, 0, 0))
        release = parse_manifest(manifest(version='0.5.0'), 'https://updates.invalid/latest.json')
        self.assertFalse(release.newer_than('0.5.0'))
        self.assertFalse(release.newer_than('0.6.0'))
        self.assertTrue(release.newer_than('0.4.1'))
        for value in ('../1.0.0', '1.2', '01.2.3', '1.2.3-beta', '1.2.3.4', None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                version_tuple(value)

    def test_invalid_schemes_credentials_fragments_and_redirects_are_rejected(self):
        for url in ('http://updates.invalid/file', 'file:///C:/a', 'https://u:p@host/file',
                    'https://host/a#part', 'https://host/\r\nX:a', 'https://host:99999/a',
                    'https://host\\bad/file', 'https://host/空格'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                https_url(url)
        handler = HTTPSRedirectHandler()
        with self.assertRaises(ValueError):
            handler.redirect_request(Request('https://updates.invalid/file'), None, 302, '', {}, 'http://host/bad')

    def test_schema_size_digest_and_notes_validation(self):
        for patch in ({'schema': True}, {'schema': 2}, {'format': 'wrong'}, {'notes': []}):
            document = manifest()
            document.update(patch)
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                parse_manifest(document, 'https://updates.invalid/latest.json')
        for patch in ({'size': True}, {'size': 0}, {'size': MAX_PACKAGE + 1}, {'sha256': 'bad'}, {'url': 'http://host/a'}):
            document = manifest()
            document['windows_x64'].update(patch)
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                parse_manifest(document, 'https://updates.invalid/latest.json')

    def test_manifest_relative_asset_pins_final_redirected_release(self):
        opener = Mock(return_value=Response(json.dumps(manifest()).encode('utf-8')))
        release = fetch_release('https://updates.invalid/releases/latest/download/latest.json', opener=opener)
        self.assertEqual(release.url, 'https://updates.invalid/releases/v0.6.0/HaloTruckDash-v0.6.0.zip')
        self.assertEqual(release.notes, '测试更新说明')

    def test_manifest_invalid_content_too_large_and_https_downgrade(self):
        for content in (b'<html>Error</html>', b'{' + b' ' * MAX_MANIFEST):
            with self.assertRaises(ValueError):
                fetch_release('https://updates.invalid/latest.json', opener=lambda *args: Response(content))
        with self.assertRaises(ValueError):
            fetch_release('https://updates.invalid/latest.json', opener=lambda *args: Response(b'{}', 'http://host/a'))

    def test_github_signed_cdn_does_not_break_relative_release_asset(self):
        content = json.dumps(manifest()).encode('utf-8')
        cdn = 'https://release-assets.githubusercontent.com/github-production-release-asset/123/random?token=test'
        for source, tag in [('https://github.com/owner/repo/releases/latest/download/latest.json', 'v0.6.0'),
                            ('https://github.com/owner/repo/releases/download/custom-tag/latest.json', 'custom-tag')]:
            with self.subTest(source=source):
                release = fetch_release(source, opener=lambda *args: Response(content, cdn))
                self.assertEqual(release.url, f'https://github.com/owner/repo/releases/download/{tag}/HaloTruckDash-v0.6.0.zip')

    def test_cancel_before_check_never_contacts_network(self):
        cancel, opener = threading.Event(), Mock()
        cancel.set()
        with self.assertRaises(UpdateCancelled):
            fetch_release('https://updates.invalid/latest.json', cancel, opener=opener)
        opener.assert_not_called()

    def test_download_verifies_bytes_and_reuses_complete_cache(self):
        content = package_bytes()
        release = parse_manifest(manifest(content), 'https://updates.invalid/latest.json')
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'research') as temporary:
            progress = []
            result = download_release(release, temporary, progress=lambda *args: progress.append(args),
                opener=lambda *args: Response(content, release.url, {'Content-Length': str(len(content))}))
            self.assertEqual(result.read_bytes(), content)
            self.assertEqual(progress[-1], (len(content), len(content)))
            self.assertFalse(list(Path(temporary).glob('*.part')))
            opener = Mock(side_effect=AssertionError('must reuse verified cache'))
            self.assertEqual(download_release(release, temporary, opener=opener), result)
            opener.assert_not_called()

    def test_bad_or_interrupted_download_does_not_replace_previous_file(self):
        content = package_bytes()
        release = parse_manifest(manifest(content), 'https://updates.invalid/latest.json')
        bad_responses = [(content[:-1], {}), (content + b'x', {}),
                         (b'x' * len(content), {}), (content, {'Content-Length': '1'})]
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'research') as temporary:
            destination = Path(temporary) / release.filename
            destination.write_bytes(b'previous file')
            for bad, headers in bad_responses:
                with self.subTest(length=len(bad), headers=headers), self.assertRaises(ValueError):
                    download_release(release, temporary, opener=lambda *args: Response(bad, release.url, headers))
                self.assertEqual(destination.read_bytes(), b'previous file')
                self.assertFalse(list(Path(temporary).glob('*.part')))
            class Broken(Response):
                def read(self, size=-1):
                    raise URLError('disconnected')
            with self.assertRaises(URLError):
                download_release(release, temporary, opener=lambda *args: Broken(content, release.url))
            self.assertEqual(destination.read_bytes(), b'previous file')
            self.assertFalse(list(Path(temporary).glob('*.part')))

    def test_cancel_during_download_cleans_partial(self):
        content, cancel = package_bytes(), threading.Event()
        release = parse_manifest(manifest(content), 'https://updates.invalid/latest.json')
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'research') as temporary:
            with self.assertRaises(UpdateCancelled):
                download_release(release, temporary, cancel, lambda *args: cancel.set(),
                                 opener=lambda *args: Response(content, release.url))
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_rejects_html_and_zip_that_could_overwrite_profile_or_escape(self):
        for content in (b'<html>error</html>', package_bytes('data/settings.json'),
                        package_bytes('../escape'), package_bytes('C:/escape')):
            release = parse_manifest(manifest(content), 'https://updates.invalid/latest.json')
            with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'research') as temporary:
                with self.assertRaises(ValueError):
                    download_release(release, temporary, opener=lambda *args: Response(content, release.url))
                self.assertEqual(list(Path(temporary).iterdir()), [])


if __name__ == '__main__':
    unittest.main()
