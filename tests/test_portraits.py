"""Offline portrait resource regression tests; all identities and URLs are fixtures."""
import copy
import hashlib
import io
import json
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

from event_brief import pdf
from event_brief.core import render_html, validate


def fixture(url='https://example.com/portrait.png'):
    return {
        'schema_version': 'event_brief.v1',
        'event': {'title': 'Fictional offline test', 'date': '2026-10-10', 'location': 'Fixture', 'host': 'Fixture'},
        'video_intake': {'validation_state': 'not_available', 'frames': [], 'limitation': 'Fictional fixture; no video supplied'},
        'name_exclusions': [],
        'people': [{
            'name': 'Taylor Example', 'visual_confidence': None, 'identity_status': 'confirmed',
            'research_attempts': [{'route': 'fictional fixture', 'query_or_note': 'No real research performed'}],
            'evidence': [{'id': 's1', 'title': 'Fictional profile', 'url': 'https://example.com/profile', 'source_type': 'fixture', 'retrieved_at': '2026-10-10'}],
            'claims': {},
            'portrait': {'state': 'verified_public', 'image_url': url, 'page_url': 'https://example.com/profile', 'source_id': 's1', 'verification_rationale': 'Fictional test only'},
        }],
    }


class OfflinePortraitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        from PIL import Image
        image = io.BytesIO()
        Image.new('RGB', (8, 8), 'green').save(image, format='PNG')
        self.raw = image.getvalue()
        (self.root / 'portrait.png').write_bytes(self.raw)
        self.portrait = {'local_asset': 'portrait.png', 'local_asset_sha256': hashlib.sha256(self.raw).hexdigest()}

    def tearDown(self):
        self.temp.cleanup()

    def test_valid_local_raster(self):
        raw = pdf.load_local_portrait(self.portrait, self.root)
        self.assertTrue(raw.startswith(b'\x89PNG'))

    def test_metadata_removed_from_pixels_and_html(self):
        import base64
        import re
        from PIL import Image, PngImagePlugin
        from event_brief.cli import main
        marker = 'SYNTHETIC_PRIVATE_METADATA'
        image = Image.new('RGB', (8, 8), 'green')
        metadata = PngImagePlugin.PngInfo(); metadata.add_text('Description', marker)
        exif = Image.Exif(); exif[270] = marker
        portrait_path = self.root / 'portrait.png'
        image.save(portrait_path, icc_profile=marker.encode(), exif=exif, pnginfo=metadata)
        self.portrait['local_asset_sha256'] = hashlib.sha256(portrait_path.read_bytes()).hexdigest()
        with Image.open(portrait_path) as original:
            self.assertEqual(original.info['icc_profile'], marker.encode())
            self.assertEqual(original.getexif()[270], marker)
            self.assertEqual(original.info['Description'], marker)
        data = fixture(); data['people'][0]['portrait'].update(self.portrait)
        source = self.root / 'brief.json'; source.write_text(json.dumps(data))
        output = self.root / 'brief.html'
        self.assertEqual(main(['render', str(source), str(output), '--format', 'html', '--portrait-dir', str(self.root)]), 0)
        encoded = re.search(r'data:image/png;base64,([A-Za-z0-9+/=]+)', output.read_text()).group(1)
        for raw in (pdf.load_local_portrait(self.portrait, self.root), base64.b64decode(encoded)):
            with Image.open(io.BytesIO(raw)) as clean:
                clean.load()
                self.assertEqual(clean.info, {})
                self.assertEqual(dict(clean.getexif()), {})
                self.assertEqual(clean.getpixel((0, 0)), (0, 128, 0))

    def test_reject_path_variants(self):
        for name in ('../portrait.png', '/etc/passwd', 'nested/portrait.png', '..', 'https://example.com/x', 'nested\\x'):
            with self.subTest(name=name), self.assertRaises((ValueError, OSError)):
                pdf.load_local_portrait({**self.portrait, 'local_asset': name}, self.root)

    def test_reject_symlink(self):
        (self.root / 'alias.png').symlink_to(self.root / 'portrait.png')
        with self.assertRaises(OSError):
            pdf.load_local_portrait({**self.portrait, 'local_asset': 'alias.png'}, self.root)

    def test_reject_checksum(self):
        with self.assertRaises(ValueError):
            pdf.load_local_portrait({**self.portrait, 'local_asset_sha256': '0' * 64}, self.root)

    def test_reject_size_and_pixels(self):
        with patch.object(pdf, 'MAX_PORTRAIT_BYTES', 4), self.assertRaises(ValueError):
            pdf.load_local_portrait(self.portrait, self.root)
        with patch.object(pdf, 'MAX_PORTRAIT_PIXELS', 4), self.assertRaises(ValueError):
            pdf.load_local_portrait(self.portrait, self.root)

    def test_missing_explicit_directory(self):
        with self.assertRaises(ValueError):
            pdf.load_local_portrait(self.portrait, None)

    def test_reject_non_raster(self):
        raw = b'<svg xmlns="http://www.w3.org/2000/svg"><image href="http://127.0.0.1/"/></svg>'
        (self.root / 'evil.svg').write_bytes(raw)
        with self.assertRaises((ValueError, OSError)):
            pdf.load_local_portrait({'local_asset': 'evil.svg', 'local_asset_sha256': hashlib.sha256(raw).hexdigest()}, self.root)

    def test_validation_checks_local_asset(self):
        data = fixture(); data['people'][0]['portrait'].update(self.portrait)
        self.assertEqual(validate(data)[0], [])
        for fields in ({'local_asset': '../x'}, {'local_asset': 'evil\x00.png'}, {'local_asset_sha256': 'incorrect'}, {'state': 'not_found'}):
            bad = copy.deepcopy(data); bad['people'][0]['portrait'].update(fields)
            self.assertTrue(validate(bad)[0])

    def test_malformed_source_urls_rejected(self):
        for url in ('https://@example.com/image', 'https://example.com:bad/image', 'https://example.com:99999/image'):
            data = fixture(url)
            self.assertTrue(validate(data)[0])

    def test_remote_urls_never_requested_or_redirected(self):
        urls = ['http://127.0.0.1/image', 'http://localhost/image', 'http://10.0.0.1/image',
                'http://172.16.0.1/image', 'http://192.168.1.1/image', 'http://169.254.169.254/latest/meta-data/',
                'http://[::1]/image', 'http://[fe80::1]/image', 'https://example.com/redirect-to-private',
                'file:///etc/passwd', 'data:image/svg+xml,invalid']
        with patch('urllib.request.urlopen', side_effect=AssertionError('Network attempted')) as opened, patch.object(socket, 'create_connection', side_effect=AssertionError('Socket attempted')) as connected:
            for url in urls:
                with self.subTest(url=url):
                    data = fixture(url)
                    assets, notes = pdf.portrait_assets(data, None)
                    self.assertEqual(assets, {}); self.assertTrue(notes)
                    html, fetcher = pdf.offline_html(data, {})
                    self.assertNotIn('<img ', html)
                    with self.assertRaises(ValueError):
                        fetcher(url)
            opened.assert_not_called(); connected.assert_not_called()

    def test_missing_asset_is_explicit_and_input_is_not_embedded(self):
        html, _ = pdf.offline_html(fixture(), {})
        self.assertIn('Portrait omitted from this export', html)
        self.assertNotIn('application/json', html)
        self.assertNotIn('No real research performed', html)

    def test_loader_serves_only_preloaded_bytes(self):
        html, fetcher = pdf.offline_html(fixture(), {0: self.raw})
        self.assertIn('hermes-portrait:0', html)
        self.assertEqual(fetcher('hermes-portrait:0')['string'], self.raw)
        for url in ('hermes-portrait:1', 'file:///tmp/portrait.png', 'https://example.com/portrait.png'):
            with self.assertRaises(ValueError):
                fetcher(url)

    def test_reportlab_embeds_local_image_without_network(self):
        from pypdf import PdfReader
        with patch('urllib.request.urlopen', side_effect=AssertionError('Network attempted')) as opened, patch.object(socket, 'create_connection', side_effect=AssertionError('Socket attempted')) as connected:
            data = fixture('http://169.254.169.254/metadata')
            data['people'][0]['portrait'].update(self.portrait)
            assets, notes = pdf.portrait_assets(data, self.root)
            self.assertEqual(notes, [])
            output = self.root / 'brief.pdf'
            pdf.reportlab_pdf(data, output, assets)
            reader = PdfReader(output)
            self.assertGreater(sum(len(page.images) for page in reader.pages), 0)
            self.assertGreater(sum(len(page.get('/Annots', [])) for page in reader.pages), 0)
            opened.assert_not_called(); connected.assert_not_called()


if __name__ == '__main__':
    unittest.main()
