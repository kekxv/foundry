"""Host file permissions, path restrictions and special-file deadline regression."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_distribution import BIN
from test_distribution import command
from test_distribution import ROOT
from test_distribution import SUFFIX


class HostFiles(unittest.TestCase):

    def test_permissions_paths_and_special_files(self):
        with tempfile.TemporaryDirectory() as directory:
            d = Path(directory)
            ext = d / 'extension'
            ext.mkdir()
            data = d / 'state'
            m = json.loads(
                (ROOT /
                 'extensions/text-utils/0.1.0/manifest.json').read_text())
            m['id'] = 'file-test'
            m['permissions'] = ['filesystem.read', 'filesystem.write']
            m['capabilities']['normalize']['input'] = {}
            m['capabilities']['normalize']['output'] = {}
            (ext / 'manifest.json').write_text(json.dumps(m))
            (ext / 'main.js').write_text(
                'export async function normalize({path,write}){if(write!==undefined)return await host.fs.writeText(path,write);return await host.fs.readText(path)}'
            )
            cli = [
                BIN / ('foundry' + SUFFIX), '--data-dir', data, '--timeout-ms',
                '200', 'dev', 'run', ext, 'normalize'
            ]
            args = ['--grant', 'filesystem.read', '--grant', 'filesystem.write']
            command(*cli, '--input', '{"path":"x"}', ok=False)
            command(*cli, *args, '--input', '{"path":"ok.txt","write":"hello"}')
            self.assertEqual(
                json.loads(
                    command(*cli, *args, '--input',
                            '{"path":"ok.txt"}').stdout), 'hello')
            command(*cli, *args, '--input', '{"path":"../escape"}', ok=False)
            if os.name != 'nt':
                state = data / 'data/file-test'
                (state / 'link').symlink_to(d)
                command(*cli,
                        *args,
                        '--input',
                        '{"path":"link/escape","write":"no"}',
                        ok=False)
                fifo = state / 'fifo'
                os.mkfifo(fifo)
                # An unbounded synchronous open would hang beyond this external watchdog.
                result = subprocess.run([
                    str(x) for x in [*cli, *args, '--input', '{"path":"fifo"}']
                ],
                                        cwd=ROOT,
                                        capture_output=True,
                                        text=True,
                                        timeout=2)
                self.assertNotEqual(result.returncode, 0)


if __name__ == '__main__':
    unittest.main()
