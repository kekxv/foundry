"""Real Git snapshot tests for trusted PR reports, without executing extension code."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from extension_diff import generate_report
from extension_diff import inline
from extension_diff import render_markdown
from registry import read_yaml


class DiffTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='foundry-diff-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git('init', '-q')
        self.git('config', 'user.name', 'Foundry Test')
        self.git('config', 'user.email', 'test@example.invalid')
        self.add_version('1.0.0')
        self.base = self.commit()

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.root), *args],
                              check=True,
                              capture_output=True,
                              text=True).stdout.strip()

    def write(self, path, content):
        path = self.root / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')

    def add_version(self, version, permissions=None):
        root = f'extensions/demo/{version}'
        self.write(
            root + '/manifest.json',
            json.dumps(
                {
                    'id': 'demo',
                    'version': version,
                    'type': 'javascript',
                    'platforms': ['any'],
                    'permissions': permissions or [],
                    'capabilities': {
                        'greet': {
                            'description': 'hi'
                        }
                    }
                },
                indent=2))
        self.write(root + '/main.js',
                   'export async function greet(){return "' + version + '"}\n')
        self.write(
            root + '/presubmit.yml',
            'matrix:\n  platform: [linux-x64, windows-x64]\ntasks: {}\n')
        versions = sorted(p.name
                          for p in (self.root / 'extensions/demo').iterdir()
                          if p.is_dir())
        self.write(
            'extensions/demo/metadata.json',
            json.dumps({
                'id': 'demo',
                'versions': versions,
                'yanked_versions': {}
            }))

    def commit(self):
        self.git('add', '-A')
        self.git('commit', '-qm', 'fixture')
        return self.git('rev-parse', 'HEAD')

    def test_new_version_compares_previous_trusted_version_and_permissions(
            self):
        self.add_version('2.0.0', ['process.spawn'])
        self.commit()
        report = generate_report(self.root, self.base)
        change = report['versions'][0]
        self.assertEqual((change['id'], change['version'], change['status'],
                          change['baseline']),
                         ('demo', '2.0.0', 'added', '1.0.0'))
        self.assertEqual(change['manifest']['permissions']['added'],
                         ['process.spawn'])
        self.assertIn('-export async function greet(){return "1.0.0"}',
                      render_markdown(report))
        self.assertIn('process.spawn', render_markdown(report))

    def test_plugin_mode_and_contract_changes_are_visible(self):
        self.add_version('2.0.0')
        path = self.root / 'extensions/demo/2.0.0/manifest.json'
        manifest = json.loads(path.read_text())
        manifest['plugin'] = {
            'kind': 'camera',
            'mode': 'mock',
            'transport': 'mock',
            'contract': 'foundry.camera.v1'
        }
        path.write_text(json.dumps(manifest))
        self.commit()
        change = generate_report(self.root, self.base)['versions'][0]
        self.assertEqual(change['manifest']['plugin']['new']['mode'], 'mock')

    def test_multiple_new_versions_use_base_not_candidate_history(self):
        self.add_version('2.0.0')
        self.add_version('3.0.0')
        self.commit()
        report = generate_report(self.root, self.base)
        self.assertEqual(
            [(v['version'], v['baseline']) for v in report['versions']],
            [('2.0.0', '1.0.0'), ('3.0.0', '1.0.0')])

    def test_metadata_only_yank_and_deleted_version_stay_visible(self):
        self.write(
            'extensions/demo/metadata.json',
            json.dumps({
                'id': 'demo',
                'versions': ['1.0.0'],
                'yanked_versions': {
                    '1.0.0': 'unsafe'
                }
            }))
        self.commit()
        report = generate_report(self.root, self.base)
        self.assertEqual(report['versions'], [])
        self.assertIn('unsafe', render_markdown(report))
        import shutil
        shutil.rmtree(self.root / 'extensions/demo/1.0.0')
        self.commit()
        report = generate_report(self.root, self.base)
        self.assertEqual(report['versions'][0]['status'], 'deleted')

    def test_modified_historical_version_not_hidden_by_immutability_check(self):
        self.write('extensions/demo/1.0.0/main.js',
                   'throw new Error("modified")\n')
        self.commit()
        change = generate_report(self.root, self.base)['versions'][0]
        self.assertEqual((change['status'], change['baseline']),
                         ('modified', '1.0.0'))
        self.assertIn(
            'modified',
            render_markdown({
                'base': self.base,
                'head': 'a' * 40,
                'versions': [change],
                'metadata': []
            }))

    def test_markdown_fences_html_and_filenames_are_safe(self):
        self.write('extensions/demo/1.0.0/main.js',
                   '```\n<script>bad</script>\n::error::untrusted\n')
        self.write('extensions/demo/1.0.0/evil&name.js', 'export const x=1')
        self.commit()
        text = render_markdown(generate_report(self.root, self.base))
        self.assertIn('### <code>evil&amp;name.js</code>', text)
        self.assertEqual(inline('evil|<img>'),
                         '<code>evil&#124;&lt;img&gt;</code>')
        self.assertIn(r'\[click\]\(https://evil\)',
                      inline('[click](https://evil)'))
        self.assertNotIn('### evil|<img>', text)
        self.assertIn('````diff', text)

    def test_binary_large_files_and_total_report_limit(self):
        version = self.root / 'extensions/demo/1.0.0'
        (version / 'binary.dat').write_bytes(b'\0\xff\xfe')
        (version / 'large.txt').write_bytes(b'x' * 300000)
        self.commit()
        text = render_markdown(generate_report(self.root, self.base))
        self.assertIn('binary', text.lower())
        self.assertIn('omitted', text.lower())
        self.assertLess(len(text.encode()), 256000)

    def test_missing_base_and_symlinks_fail_closed(self):
        with self.assertRaises((ValueError, subprocess.CalledProcessError)):
            generate_report(self.root, 'f' * 40)
        path = self.root / 'extensions/demo/1.0.0/link'
        try:
            path.symlink_to('/etc/passwd')
        except (OSError, NotImplementedError):
            self.skipTest('symlink creation unavailable')
        self.commit()
        with self.assertRaises(ValueError):
            generate_report(self.root, self.base)

    def test_cli_outputs_markdown_and_json_without_logging_untrusted_diff(self):
        import sys
        self.write('extensions/demo/1.0.0/main.js',
                   '::error::untrusted workflow command\n')
        self.commit()
        tool = Path(__file__).resolve().with_name('extension_diff.py')
        output = self.root / 'report'
        result = subprocess.run([
            sys.executable,
            str(tool), '--root',
            str(self.root), '--base', self.base, '--output',
            str(output / 'report.md'), '--json-output',
            str(output / 'report.json')
        ],
                                capture_output=True,
                                text=True,
                                timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('::error::', result.stdout + result.stderr)
        self.assertIn('::error::', (output / 'report.md').read_text())
        self.assertEqual(
            json.loads((output / 'report.json').read_text())['base'], self.base)

    def test_uncommitted_candidate_files_cannot_change_snapshot_report(self):
        self.write('extensions/demo/1.0.0/main.js',
                   'uncommitted candidate content')
        report = generate_report(self.root, self.base)
        self.assertEqual(report['versions'], [])

    def test_no_change_or_shared_runtime_change_has_explicit_empty_report(self):
        report = generate_report(self.root, self.base)
        self.assertEqual(report['versions'], [])
        self.write('crates/new.rs', '// shared change')
        self.commit()
        self.assertIn('No extension',
                      render_markdown(generate_report(self.root, self.base)))

    def test_pr_packages_include_new_versions_and_skip_existing_packages(self):
        self.add_version('2.0.0')
        self.write('crates/new.rs', '// shared change')
        self.commit()
        tool = Path(__file__).resolve().with_name('extension_matrix.py')
        result = subprocess.check_output([
            sys.executable,
            str(tool), '--root',
            str(self.root), '--base', self.base, '--package-only'
        ],
                                         text=True,
                                         timeout=30)
        self.assertEqual(json.loads(result), [['demo', '2.0.0']])


class WorkflowGateTests(unittest.TestCase):

    def test_required_gate_workflow_runs_for_documentation_only_prs(self):
        root = Path(__file__).resolve().parents[1]
        workflow = read_yaml(root / '.github/workflows/extensions.yml')
        events = workflow.get('on', workflow.get(True))
        self.assertEqual(set(events), {'pull_request'})
        pull_request = events['pull_request'] or {}
        self.assertNotIn('paths', pull_request)
        self.assertNotIn('paths-ignore', pull_request)

    def test_trusted_checkout_is_a_sibling_not_inside_candidate_tree(self):
        root = Path(__file__).resolve().parents[1]
        workflow = read_yaml(root / '.github/workflows/extensions.yml')
        for job in ('diff', 'matrix'):
            steps = workflow['jobs'][job]['steps']
            checkouts = [
                s for s in steps
                if s.get('uses', '').startswith('actions/checkout@')
            ]
            candidate = checkouts[0]['with'].get('path', '.')
            trusted = checkouts[1]['with']['path']
            self.assertNotEqual(
                candidate, '.',
                'PR tree must not own the trusted checkout parent')
            self.assertNotEqual(candidate, trusted)
            self.assertFalse(trusted.startswith(candidate + '/'))

    @unittest.skipIf(
        os.name == 'nt',
        'Aggregate gate runs on Ubuntu; exercise its bash on Unix')
    def test_gate_fails_closed_for_failed_cancelled_and_unexpected_skips(self):
        root = Path(__file__).resolve().parents[1]
        workflow = read_yaml(root / '.github/workflows/extensions.yml')
        script = workflow['jobs']['checks']['steps'][0]['run']
        cases = [
            ('success', 'success', 'success', 'true', True),
            ('success', 'success', 'skipped', 'false', True),
            ('failure', 'success', 'success', 'true', False),
            ('success', 'failure', 'skipped', '', False),
            ('success', 'cancelled', 'skipped', '', False),
            ('success', 'success', 'failure', 'true', False),
            ('success', 'success', 'cancelled', 'true', False),
            ('success', 'success', 'skipped', 'true', False),
            ('skipped', 'success', 'success', 'true', False),
            ('success', 'success', 'skipped', '', False),
        ]
        with tempfile.TemporaryDirectory() as directory:
            for diff, matrix, test, changes, expected in cases:
                with self.subTest(diff=diff,
                                  matrix=matrix,
                                  test=test,
                                  changes=changes):
                    env = dict(os.environ,
                               DIFF_RESULT=diff,
                               MATRIX_RESULT=matrix,
                               TEST_RESULT=test,
                               HAS_CHANGES=changes,
                               GITHUB_STEP_SUMMARY=str(
                                   Path(directory) / 'summary'))
                    result = subprocess.run(
                        ['bash', '-e', '-o', 'pipefail', '-c', script],
                        env=env,
                        capture_output=True,
                        text=True,
                        timeout=10)
                    self.assertEqual(result.returncode == 0, expected,
                                     result.stderr)


if __name__ == '__main__':
    unittest.main()
