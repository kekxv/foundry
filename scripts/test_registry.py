"""Regression tests for versioned registry configuration and CI trust boundaries."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from build_extensions import check_external_size
from registry import merge_packages
from registry import partition_packages
from registry import published_packages
from registry import Registry
from registry import safe_environment


class RegistryTests(unittest.TestCase):

    def test_curl_checks_only_the_final_response_size(self):
        url = 'https://downloads.example.org/demo.zip'
        limit = 250 * 1024**2
        redirect = 'HTTP/1.1 302 Found\r\nContent-Length: 0\r\n\r\n'
        with patch('build_extensions.subprocess.run') as curl:
            curl.return_value.returncode = 0

            def set_response(headers):
                curl.return_value.stdout = (redirect + 'HTTP/2 200\r\n' +
                                            headers + '\r\n')

            set_response(f'content-length: {limit}\r\n')
            self.assertEqual(check_external_size(url), limit)
            self.assertIn('--head', curl.call_args.args[0])
            for headers in [
                    f'Content-Length: {limit + 1}\r\n',
                    'Content-Length: 0\r\n',
                    'Transfer-Encoding: chunked\r\n',
                    'Content-Length: 1024\r\nContent-Length: 2048\r\n',
            ]:
                set_response(headers)
                with self.assertRaises(ValueError):
                    check_external_size(url)

    def test_yaml_package_size_is_optional_and_estimates_are_not_pins(self):
        with tempfile.TemporaryDirectory() as d:
            registry, version = self.registry(Path(d))
            url = 'https://example.org/demo.zip'
            digest = 'ab' * 32
            yaml = f'any:\n  url: {url}\n  sha256: "{digest}"\n'
            config = version / 'packages.yaml'
            expected = {'any': {'url': url, 'sha256': digest}}
            for suffix in ('', '  size: 1000\n', '  size: 262144001\n'):
                config.write_text(yaml + suffix, encoding='utf-8')
                self.assertEqual(registry.external_packages('demo', '1.0.0'),
                                 expected)
            (version / 'packages.json').write_text('{}', encoding='utf-8')
            with self.assertRaises(ValueError):
                registry.external_packages('demo', '1.0.0')

    def registry(self, root):
        version = root / 'extensions/demo/1.0.0'
        version.mkdir(parents=True)
        (version.parent / 'metadata.json').write_text(
            json.dumps({
                'id': 'demo',
                'versions': ['1.0.0'],
                'yanked_versions': {}
            }))
        (version / 'manifest.json').write_text(
            json.dumps({
                'id': 'demo',
                'version': '1.0.0',
                'type': 'javascript',
                'platforms': ['any'],
                'capabilities': {
                    'greet': {}
                },
                'permissions': []
            }))
        (version /
         'main.js').write_text('export async function greet(){return 1}')
        (version / 'presubmit.yml').write_text(
            'matrix:\n  platform: [linux-x64]\ntasks:\n  greet:\n    capability: greet\n    input: {}\n    expect: 1\n'
        )
        return Registry(root), version

    def test_official_platforms_match_workflows_schema_and_extensions(self):
        from registry import read_yaml
        from registry import RUNNERS
        root = Path(__file__).resolve().parents[1]
        expected = {'windows-x64', 'macos-arm64', 'linux-x64', 'linux-arm64'}
        self.assertEqual(set(RUNNERS), expected)
        for file, job in [('ci.yml', 'rust'), ('release.yml', 'build')]:
            workflow = read_yaml(root / '.github/workflows' / file)
            entries = workflow['jobs'][job]['strategy']['matrix']['include']
            self.assertEqual({row['platform'] for row in entries}, expected)
        registry = Registry(root)
        for id, version in [
            (id, '0.1.0') for id in ('text-utils', 'file-digest', 'native-math')
        ]:
            self.assertEqual(
                set(registry.config(id, version)['matrix']['platform']),
                expected)
            manifest = registry.manifest(id, version)
            if manifest['type'] != 'javascript':
                self.assertEqual(set(manifest['platforms']), expected)
        schema = json.loads((root / 'schemas/manifest.schema.json').read_text())
        self.assertEqual(
            set(schema['properties']['platforms']['items']['enum']),
            expected | {'any'})

    def test_config_drives_platforms_and_discovers_versions(self):
        with tempfile.TemporaryDirectory() as d:
            r, v = self.registry(Path(d))
            self.assertEqual(r.names(), ['demo'])
            self.assertEqual(r.versions('demo'), ['1.0.0'])
            self.assertEqual(
                r.config('demo', '1.0.0')['matrix']['platform'], ['linux-x64'])

    def test_external_packages_require_complete_https_pins(self):
        with tempfile.TemporaryDirectory() as d:
            registry, version = self.registry(Path(d))
            record = {
                'url': 'https://downloads.example.org/demo.zip',
                'sha256': 'ab' * 32,
                'size': 1024,
            }
            pins = version / 'packages.json'
            pins.write_text(json.dumps({'any': record}))
            self.assertEqual(registry.external_packages('demo', '1.0.0'),
                             {'any': {
                                 k: record[k] for k in ('url', 'sha256')
                             }})
            for invalid in [
                {},
                {
                    'linux-x64': record
                },
                {
                    'any': dict(record, url='http://example.org/demo.zip')
                },
                {
                    'any': dict(record, url='https://key@example.org/demo.zip')
                },
                {
                    'any': dict(record, sha256='missing')
                },
                {
                    'any': dict(record, size=True)
                },
                {
                    'any': dict(record, size=0)
                },
            ]:
                pins.write_text(json.dumps(invalid))
                with self.assertRaises(ValueError):
                    registry.external_packages('demo', '1.0.0')

    def test_rejects_unknown_runner_shell_tasks_duplicate_keys_and_paths(self):
        with tempfile.TemporaryDirectory() as d:
            r, v = self.registry(Path(d))
            original = (v / 'presubmit.yml').read_text()
            for text in [
                    original.replace('linux-x64', 'self-hosted'),
                    original + 'command: curl evil\n', original + 'tasks: {}\n',
                    original +
                    'build:\n  cargo_manifest: ../Cargo.toml\n  artifacts: []\n',
                    original.replace('expect: 1', 'expect: &secret 1')
            ]:
                (v / 'presubmit.yml').write_text(text)
                with self.assertRaises(ValueError):
                    r.config('demo', '1.0.0')

    def test_yanked_versions_not_selected_and_new_versions_detected(self):
        with tempfile.TemporaryDirectory() as d:
            r, v = self.registry(Path(d))
            import shutil
            shutil.copytree(v, v.parent / '2.0.0')
            m = json.loads((v / 'manifest.json').read_text())
            m['version'] = '2.0.0'
            (v.parent / '2.0.0/manifest.json').write_text(json.dumps(m))
            (v.parent / 'metadata.json').write_text(
                json.dumps({
                    'id': 'demo',
                    'versions': ['1.0.0', '2.0.0'],
                    'yanked_versions': {
                        '1.0.0': 'bad'
                    }
                }))
            self.assertEqual(r.versions('demo'), ['2.0.0'])
            self.assertEqual(r.versions('demo', include_yanked=True),
                             ['1.0.0', '2.0.0'])

    def test_immutable_merge_keeps_history_and_rejects_overwrite(self):
        old = {
            'id': 'demo',
            'version': '1.0.0',
            'platform': 'any',
            'sha256': 'a',
            'size': 1,
            'url': 'old'
        }
        new = dict(old, version='2.0.0', sha256='b')
        self.assertEqual(len(merge_packages([old], [new])), 2)
        with self.assertRaises(ValueError):
            merge_packages([old], [dict(old, sha256='evil')])

    def test_yank_unyank_preserves_original_signed_artifacts(self):
        old = {
            'id': 'demo',
            'version': '1.0.0',
            'platform': 'any',
            'sha256': 'a',
            'size': 1,
            'url': 'original'
        }
        active, withdrawn = partition_packages([old], set())
        self.assertEqual(active, [])
        history = published_packages({
            'packages': active,
            'withdrawnPackages': withdrawn
        })
        restored, _ = partition_packages(history, {('demo', '1.0.0')})
        self.assertEqual(restored, [old])
        with self.assertRaises(ValueError):
            merge_packages(history, [dict(old, sha256='rebuilt')])

    def test_child_environment_excludes_credentials(self):
        env = safe_environment({
            'PATH': '/bin',
            'HOME': '/tmp',
            'FOUNDRY_SIGNING_KEY': 'private',
            'GH_TOKEN': 'private',
            'GITHUB_TOKEN': 'private',
            'ACTIONS_RUNTIME_TOKEN': 'private',
            'AWS_SECRET_ACCESS_KEY': 'private'
        })
        self.assertEqual(env['PATH'], '/bin')
        self.assertNotIn('private', env.values())

    def test_change_detection_metadata_shared_and_deletion(self):
        with tempfile.TemporaryDirectory() as d:
            r, v = self.registry(Path(d))
            self.assertEqual(r.affected(['extensions/demo/1.0.0/main.js']),
                             [('demo', '1.0.0')])
            self.assertEqual(r.affected(['extensions/demo/metadata.json']),
                             [('demo', '1.0.0')])
            self.assertEqual(r.affected(['crates/foundry-runtime/src/lib.rs']),
                             [('demo', '1.0.0')])
            self.assertEqual(r.affected(['.gitattributes']),
                             [('demo', '1.0.0')])
            self.assertEqual(r.affected(['README.md']), [])
            with self.assertRaises(ValueError):
                r.affected(['extensions/demo/0.0.1/main.js'])

    def test_history_cannot_be_rewritten_or_deleted(self):
        with tempfile.TemporaryDirectory() as d:
            r, v = self.registry(Path(d))
            for path in [
                    'extensions/demo/1.0.0/main.js',
                    'extensions/demo/1.0.0/presubmit.yml'
            ]:
                with self.assertRaises(ValueError):
                    r.check_immutable([path], {'demo': ['1.0.0']})
            r.check_immutable(['extensions/demo/2.0.0/main.js'],
                              {'demo': ['1.0.0']})


if __name__ == '__main__':
    unittest.main()
