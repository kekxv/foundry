"""Verify discovery data is available independently of signed releases."""
from contextlib import chdir
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from pages_registry import checkout_pages
from pages_registry import stage_registry
from publish_catalogue import publish_catalogue
from publish_catalogue import registry_url

ROOT = Path(__file__).resolve().parents[1]


class SiteRegistryTests(unittest.TestCase):

    def test_checkout_reads_pages_without_touching_source_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            source = workspace / 'source'
            source.mkdir()
            snapshot = workspace / 'snapshot'
            snapshot.mkdir()
            with chdir(source):

                def git(*args):
                    subprocess.run(['git', *args],
                                   check=True,
                                   stdout=subprocess.DEVNULL)

                git('init', '--quiet', '--initial-branch=main')
                git('config', 'user.name', 'Foundry registry test')
                git('config', 'user.email', 'test@example.invalid')
                git('commit', '--quiet', '--allow-empty', '-m', 'Initial')
                git('clone', '--quiet', '--bare', '.',
                    str(workspace / 'remote'))
                git('remote', 'add', 'origin', str(workspace / 'remote'))
                self.assertFalse(checkout_pages(snapshot).exists())
                git('push', '--quiet', 'origin', 'HEAD:refs/heads/gh-pages')
                self.assertFalse(checkout_pages(snapshot).exists())
                git('checkout', '--quiet', '-b', 'pages-test')
                Path('registry').mkdir()
                Path('registry/index.json').write_bytes(b'published index')
                git('add', 'registry')
                git('commit', '--quiet', '-m', 'Publish registry')
                git('push', '--quiet', 'origin', 'HEAD:refs/heads/gh-pages')
                git('checkout', '--quiet', 'main')
                saved = checkout_pages(snapshot)
                self.assertEqual((saved / 'index.json').read_bytes(),
                                 b'published index')
                self.assertFalse(Path('registry').exists())

    def test_discovery_preserves_per_version_metadata_without_a_release(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            publish_catalogue(ROOT, destination)
            data = json.loads((destination / 'registry-data.json').read_bytes())
            self.assertIsNone(data['index'])
            extension = destination / 'extensions/text-utils'
            self.assertEqual(
                json.loads(
                    (extension / 'metadata.json').read_bytes())['versions'],
                ['0.1.0'])
            self.assertEqual(
                (extension / '0.1.0/manifest.json').read_bytes(),
                (ROOT /
                 'extensions/text-utils/0.1.0/manifest.json').read_bytes())
            self.assertFalse((destination / 'index.json').exists())

    def test_pages_updates_preserve_published_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            previous = root / 'previous'
            packages = previous / 'packages'
            packages.mkdir(parents=True)
            (packages / 'demo-1.0.0-any.zip').write_bytes(b'old')
            (previous / 'index.json').write_text('{"sequence": 4}')
            (previous / 'index.json.sig').write_bytes(b'previous signature')
            (previous / 'root.json').write_bytes(b'previous public root')
            out = root / 'output'
            stage_registry(previous, out)
            self.assertEqual((out / 'index.json.sig').read_bytes(),
                             b'previous signature')
            self.assertEqual((out / 'packages/demo-1.0.0-any.zip').read_bytes(),
                             b'old')

            signed = root / 'signed'
            signed.mkdir()
            archive = signed / 'demo-2.0.0-any.zip'
            archive.write_bytes(b'new')
            (signed / 'index.json.sig').write_bytes(b'new signature')
            (signed / 'index.json').write_text(
                json.dumps({
                    'sequence':
                        5,
                    'packages': [{
                        'url':
                            registry_url('owner/foundry').replace(
                                'index.json', 'packages/' + archive.name),
                        'size':
                            3,
                        'sha256':
                            hashlib.sha256(b'new').hexdigest(),
                    }],
                }))
            public_root = root / 'root.json'
            public_root.write_bytes(b'new public root')
            next_out = root / 'next'
            stage_registry(previous, next_out, signed, public_root,
                           'owner/foundry')
            self.assertEqual((next_out / 'index.json').read_bytes(),
                             (signed / 'index.json').read_bytes())
            self.assertEqual(
                (next_out / 'packages/demo-1.0.0-any.zip').read_bytes(), b'old')
            self.assertEqual(
                (next_out / 'packages/demo-2.0.0-any.zip').read_bytes(), b'new')
            stage_registry(next_out, root / 'retry', signed, public_root,
                           'owner/foundry')
            self.assertEqual((root / 'retry/index.json').read_bytes(),
                             (next_out / 'index.json').read_bytes())
            (signed / 'index.json.sig').write_bytes(b'conflicting signature')
            with self.assertRaisesRegex(ValueError, 'sequence'):
                stage_registry(next_out, root / 'replay', signed, public_root,
                               'owner/foundry')

    def test_project_and_root_sites_share_release_client_urls(self):
        self.assertEqual(registry_url('kekxv/foundry'),
                         'https://kekxv.github.io/foundry/registry/index.json')
        self.assertEqual(registry_url('kekxv/kekxv.github.io'),
                         'https://kekxv.github.io/registry/index.json')

    def test_catalogue_references_the_verified_index_without_rewriting_it(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            index = destination / 'index.json'
            original = b'{ "packages": [] }\n'
            index.write_bytes(original)
            publish_catalogue(ROOT, destination)
            catalogue = json.loads(
                (destination / 'registry-data.json').read_bytes())
            self.assertEqual(catalogue['index'], 'index.json')
            self.assertEqual(index.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
