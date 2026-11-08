"""Exercise device contracts through real QuickJS and temporary signed installs."""
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest

from test_distribution import BIN
from test_distribution import command
from test_distribution import ROOT
from test_distribution import SUFFIX

PNG = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mP4DwQACfsD/Wj6HMwAAAAASUVORK5CYII='
PLUGINS = {
    'id-card-reader': ('read-card', {}),
    'camera': ('capture', {}),
    'ocr': ('recognize', {
        'image': {
            'mimeType': 'image/png',
            'base64': PNG
        }
    }),
    'serial-port': ('exchange', {
        'message': 'PING'
    })
}


class DevicePlugins(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='foundry-devices-')
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.client = BIN / ('foundry' + SUFFIX)

    def run_plugin(self, id, capability, value, ok=True, source=None):
        source = source or ROOT / 'extensions' / id / '0.1.0'
        self.assertTrue(source.is_dir(), f'Missing official plugin {id}')
        return command(self.client,
                       '--data-dir',
                       self.directory / 'state',
                       'dev',
                       'run',
                       source,
                       capability,
                       '--input',
                       json.dumps(value),
                       ok=ok)

    def test_fixed_identity_camera_ocr_and_serial_contracts(self):
        result = {
            id: json.loads(self.run_plugin(id, cap, inp).stdout)
            for id, (cap, inp) in PLUGINS.items()
        }
        for id, value in result.items():
            self.assertEqual(value['schemaVersion'], 1)
            self.assertEqual(value['mode'], 'mock')
            self.assertTrue(value['deviceId'].startswith('mock-'))
            manifest = json.loads(
                (ROOT / 'extensions' / id /
                 '0.1.0/manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(
                manifest['capabilities'][PLUGINS[id][0]]['output'],
                json.loads(
                    (ROOT / 'schemas/plugins' /
                     f'{id}.v1.schema.json').read_text(encoding='utf-8')))
            if id != 'ocr':
                self.assertEqual(
                    json.loads(self.run_plugin(id, 'devices',
                                               {}).stdout)['devices'][0]['id'],
                    value['deviceId'])
        self.assertEqual(result['id-card-reader']['data']['idNumber'],
                         '000000199001010000')
        self.assertEqual(result['id-card-reader']['data']['name'], '模拟测试人员')
        self.assertIsNone(result['id-card-reader']['data']['photo'])
        frame = result['camera']['data']['image']
        chained = json.loads(
            self.run_plugin('ocr', 'recognize', {
                'image': frame
            }).stdout)
        self.assertEqual(chained['data']['text'], 'FOUNDRY MOCK TEXT')
        import base64
        import struct
        image = base64.b64decode(frame['base64'], validate=True)
        self.assertEqual(image[:8], b'\x89PNG\r\n\x1a\n')
        import zlib
        offset = 8
        while offset < len(image):
            size = struct.unpack('>I', image[offset:offset + 4])[0]
            chunk = image[offset + 4:offset + 8 + size]
            crc = struct.unpack('>I',
                                image[offset + 8 + size:offset + 12 + size])[0]
            self.assertEqual(crc,
                             zlib.crc32(chunk) & 0xffffffff,
                             'Camera returned corrupt PNG')
            offset += size + 12
        self.assertEqual(struct.unpack('>II', image[16:24]),
                         (frame['width'], frame['height']))
        self.assertEqual(result['ocr']['data']['text'], 'FOUNDRY MOCK TEXT')
        self.assertEqual(result['serial-port']['data']['response'], 'PONG')
        self.assertEqual(
            json.loads(
                self.run_plugin('serial-port', 'exchange', {
                    'message': 'hello'
                }).stdout)['data']['response'], 'ECHO:hello')

    def test_unknown_device_invalid_images_and_outputs_fail(self):
        for id in ['id-card-reader', 'camera']:
            cap = PLUGINS[id][0]
            error = self.run_plugin(id,
                                    cap, {'deviceId': 'mock-missing'},
                                    ok=False)
            self.assertIn('DEVICE_NOT_FOUND', error.stderr)
        self.run_plugin(
            'ocr',
            'recognize',
            {'image': {
                'mimeType': 'image/png',
                'base64': 'invalid!'
            }},
            ok=False)
        self.run_plugin('camera', 'capture', {'format': 'jpeg'}, ok=False)
        self.run_plugin('serial-port',
                        'exchange', {'message': 'x' * 257},
                        ok=False)
        source = self.directory / 'invalid-output'
        shutil.copytree(ROOT / 'extensions/id-card-reader/0.1.0', source)
        (source / 'main.js').write_text(
            'export async function readCard(){return {unexpected:true}}')
        error = self.run_plugin('id-card-reader',
                                'read-card', {},
                                ok=False,
                                source=source)
        self.assertIn('schema', error.stderr.lower())

    def test_signed_download_and_install_device_plugins(self):
        import sys
        release = BIN / ('foundry-release' + SUFFIX)
        packages = []
        for id in PLUGINS:
            out = self.directory / 'packages' / id
            command(sys.executable,
                    ROOT / 'scripts/build_extensions.py',
                    '--out',
                    out,
                    '--extension',
                    id,
                    '--version',
                    '0.1.0',
                    timeout=1200)
            packages.extend(
                json.loads(
                    (out / 'candidates.json').read_text(encoding='utf-8')))
        private = self.directory / 'test.key'
        root = self.directory / 'root.json'
        command(release, 'keygen', '--private-output', private, '--root-output',
                root, '--key-id', 'device-test')
        index = self.directory / 'index.json'
        index.write_text(
            json.dumps({
                'schemaVersion': 1,
                'sequence': 1,
                'expiresAt': int(time.time()) + 3600,
                'sourceCommit': 'a' * 40,
                'packages': packages
            }))
        command(release,
                'sign',
                '--input',
                index,
                '--output',
                str(index) + '.sig',
                '--key-id',
                'device-test',
                env=dict(
                    os.environ,
                    FOUNDRY_SIGNING_KEY=private.read_text(encoding='utf-8')))
        cli = [
            self.client, '--data-dir', self.directory / 'installed',
            '--trust-root', root, '--index', index
        ]
        for id, (cap, inp) in PLUGINS.items():
            command(*cli, 'download', id, '--output',
                    self.directory / (id + '.zip'))
            command(*cli, 'install', id)
            value = json.loads(
                command(*cli, 'run', id, cap, '--input',
                        json.dumps(inp)).stdout)
            self.assertEqual(value['mode'], 'mock')


if __name__ == '__main__':
    unittest.main()
