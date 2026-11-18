import copy
import io
from contextlib import redirect_stdout
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from event_brief.cli import main, read_input, write_new
from event_brief.core import render_html, render_markdown, validate


def fixture():
    return json.loads((Path(__file__).parents[1] / 'examples/brief.json').read_text())


class SecurityTests(unittest.TestCase):
    def test_unresolved_identity_cannot_carry_claims(self):
        data = fixture(); data['people'][0]['identity_status'] = 'ambiguous'
        self.assertTrue(validate(data)[0])

    def test_claim_must_reference_existing_source(self):
        data = fixture(); data['people'][0]['claims']['current_role']['source_ids'] = ['missing']
        self.assertTrue(validate(data)[0])

    def test_executable_links_are_rejected(self):
        for url in ['javascript:alert(1)', 'file:///etc/passwd', 'data:text/html,bad', 'https://user:pass@example.com', 'https://example.com\n/x']:
            data = fixture(); data['people'][0]['evidence'][0]['url'] = url
            self.assertTrue(validate(data)[0])

    def test_html_does_not_execute_input_or_embed_raw_records(self):
        data = fixture(); data['event']['title'] = '<img src=x onerror=alert(1)>'
        data['people'][0]['research_attempts'][0]['query_or_note'] = 'PRIVATE_RESEARCH_NOTE'
        data['unknown_field'] = 'PRIVATE_EXTRA_FIELD'
        html = render_html(data)
        self.assertNotIn('<img src=x', html)
        self.assertNotIn('PRIVATE_RESEARCH_NOTE', html)
        self.assertNotIn('PRIVATE_EXTRA_FIELD', html)
        self.assertNotIn('<script', html)
        self.assertIn('Content-Security-Policy', html)

    def test_markdown_escapes_html_and_image_syntax(self):
        data = fixture(); data['event']['title'] = '<script>bad</script> ![x](https://example.com/track)'
        markdown = render_markdown(data)
        self.assertNotIn('<script>', markdown)
        self.assertNotIn('![x](', markdown)

    def test_export_round_trip_without_network(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(socket, 'create_connection', side_effect=AssertionError('Network attempted')):
            root = Path(tmp); source = root / 'input.json'; source.write_text(json.dumps(fixture()))
            for format in ['html', 'markdown', 'pdf']:
                output = root / ('brief.' + format)
                self.assertEqual(main(['render', str(source), str(output), '--format', format]), 0)
                self.assertGreater(output.stat().st_size, 100)
                original = output.read_bytes()
                self.assertEqual(main(['render', str(source), str(output), '--format', format]), 1)
                self.assertEqual(original, output.read_bytes())
                self.assertEqual(output.stat().st_mode & 0o777, 0o600)

    def test_input_symlink_and_size_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / 'input'; source.write_bytes(b'x' * (2 * 1024 * 1024 + 1))
            with self.assertRaises(ValueError): read_input(source)
            link = root / 'link'; link.symlink_to(source)
            with self.assertRaises(OSError): read_input(link)

    def test_output_symlink_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); target = root / 'target'; target.write_text('keep')
            link = root / 'link'; link.symlink_to(target)
            with self.assertRaises(FileExistsError): write_new(link, b'changed')
            self.assertEqual(target.read_text(), 'keep')

    def test_malformed_inputs_fail_without_tracebacks(self):
        for data in [None, [], {'schema_version': []}, {'people': [None]}]:
            self.assertTrue(validate(data)[0])

    def test_dependency_error_does_not_disclose_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / 'input.json'; source.write_text(json.dumps(fixture()))
            captured = io.StringIO()
            with patch('event_brief.pdf.reportlab_pdf', side_effect=RuntimeError('PRIVATE_DETAIL')), redirect_stdout(captured):
                result = main(['render', str(source), str(root / 'out.pdf'), '--format', 'pdf'])
            self.assertEqual(result, 1)
            self.assertNotIn('PRIVATE_DETAIL', captured.getvalue())
            self.assertNotIn(str(root), captured.getvalue())
            self.assertFalse((root / 'out.pdf').exists())
