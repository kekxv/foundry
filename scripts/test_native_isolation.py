"""Compile a test-only C ABI library, exercise real libffi and crash isolation."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from test_distribution import BIN
from test_distribution import command
from test_distribution import ROOT
from test_distribution import SUFFIX


class NativeIsolation(unittest.TestCase):

    def test_typed_inputs_crash_and_timeout(self):
        with tempfile.TemporaryDirectory(prefix='foundry-native-test-') as temp:
            d = Path(temp)
            (d / 'lib').mkdir()
            manifest = json.loads(
                (ROOT /
                 'extensions/native-math/0.1.0/manifest.json').read_text())
            # Every declared target uses the same filename in this explicitly local test.
            filename = 'test.dll' if os.name == 'nt' else 'test.dylib' if os.uname(
            ).sysname == 'Darwin' else 'test.so'
            manifest['id'] = 'native-test'
            lib = manifest['libraries']['math']
            lib['paths'] = {p: 'lib/' + filename for p in manifest['platforms']}
            symbols = {
                'text': {
                    'symbol': 'text_len',
                    'parameters': ['cstring'],
                    'returns': 'u32'
                },
                'bytes': {
                    'symbol': 'buffer_sum',
                    'parameters': ['buffer'],
                    'returns': 'u32'
                },
                'crash': {
                    'symbol': 'crash',
                    'parameters': [],
                    'returns': 'void'
                },
                'spin': {
                    'symbol': 'spin',
                    'parameters': [],
                    'returns': 'void'
                },
                'log': {
                    'symbol': 'log',
                    'parameters': [],
                    'returns': 'i32'
                },
            }
            lib['symbols'] = symbols
            manifest['capabilities'] = {
                name: {
                    'description': name,
                    'export': name,
                    'input': {},
                    'output': {}
                } for name in symbols
            }
            (d / 'manifest.json').write_text(json.dumps(manifest))
            (d / 'main.js').write_text('\n'.join(
                f'export async function {name}(args){{return await host.library("math").call("{name}",args)}}'
                for name in symbols))
            rust = d / 'test.rs'
            rust.write_text('''
#[unsafe(no_mangle)] pub unsafe extern "C" fn text_len(p:*const std::ffi::c_char)->u32 { unsafe { std::ffi::CStr::from_ptr(p).to_bytes().len() as u32 } }
#[unsafe(no_mangle)] pub unsafe extern "C" fn buffer_sum(p:*const u8,n:usize)->u32 { unsafe { std::slice::from_raw_parts(p,n).iter().map(|x|*x as u32).sum() } }
#[unsafe(no_mangle)] pub extern "C" fn crash(){ std::process::abort(); }
#[unsafe(no_mangle)] pub extern "C" fn spin(){ loop { std::hint::spin_loop(); } }
#[unsafe(no_mangle)] pub extern "C" fn log()->i32 { println!("native diagnostic");eprintln!("stderr diagnostic");42 }
''')
            compiler = shutil.which('rustc') or str(
                Path.home() / '.cargo/bin/rustc')
            command(compiler, '--edition=2024', '--crate-type=cdylib', '-o',
                    d / 'lib' / filename, rust)
            cli = [
                BIN / ('foundry' + SUFFIX), '--data-dir', d / 'data',
                '--timeout-ms', '1500', 'dev', 'run', d
            ]

            def run(name, args, ok=True):
                return command(*cli,
                               name,
                               '--grant',
                               'native.call',
                               '--input',
                               json.dumps(args),
                               ok=ok)

            self.assertEqual(json.loads(run('log', []).stdout), 42)
            self.assertEqual(json.loads(run('text', ['hello']).stdout), 5)
            self.assertEqual(json.loads(run('bytes', [[1, 2, 255]]).stdout),
                             258)
            self.assertEqual(json.loads(run('bytes', [[]]).stdout), 0)
            run('text', ['bad\0string'], ok=False)
            run('bytes', [[256]], ok=False)
            run('crash', [], ok=False)
            run('spin', [], ok=False)
            # Subsequent commands still execute; test-only crash symbols are never shipped.
            self.assertEqual(json.loads(run('text', ['alive']).stdout), 5)


if __name__ == '__main__':
    unittest.main()
