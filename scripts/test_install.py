#!/usr/bin/env python3
"""Exercise the published installer against a temporary signed HTTPS release."""
import argparse
import hashlib
from http.server import SimpleHTTPRequestHandler
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import tempfile
from threading import Thread
import tomllib
import zipfile

from build_extensions import host_platform

ROOT = Path(__file__).resolve().parents[1]
PLATFORMS = ('linux-x64', 'linux-arm64', 'macos-arm64', 'windows-x64')
VERSION = tomllib.loads((ROOT / 'Cargo.toml').read_text(
    encoding='utf-8'))['workspace']['package']['version']


class QuietHandler(SimpleHTTPRequestHandler):

    def do_GET(self):
        latest = '/releases/latest/download/'
        if self.path.startswith(latest):
            self.send_response(302)
            self.send_header(
                'Location',
                self.path.replace(latest, f'/releases/download/v{VERSION}/', 1))
            self.end_headers()
        else:
            super().do_GET()

    def log_message(self, *_args):
        pass


def run_test(root, openssl):
    platform = host_platform()
    windows = platform.startswith('windows-')
    suffix = '.exe' if windows else ''
    foundry = f'foundry{suffix}'
    worker = f'foundry-worker{suffix}'
    release = ROOT / 'target/debug' / f'foundry-release{suffix}'
    www = root / 'www'
    assets = www / f'releases/download/v{VERSION}'
    assets.mkdir(parents=True)
    archive = assets / f'foundry-{VERSION}-{platform}.zip'
    binaries = root / 'binaries'
    binaries.mkdir()
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as package:
        for name in (foundry, worker):
            binary = Path(shutil.copy2(ROOT / 'target/debug' / name, binaries))
            if not windows:
                subprocess.run(['strip', '-S', binary], check=True)
            if platform == 'macos-arm64':
                subprocess.run(['codesign', '--force', '--sign', '-', binary],
                               check=True,
                               capture_output=True)
            package.write(binary, name)
        package.writestr('README.md', 'Foundry client')
    manifest = assets / 'release-manifest.json'
    data = archive.read_bytes()
    manifest.write_text(json.dumps({
        'schemaVersion': 1,
        'sourceCommit': 'a' * 40,
        'version': VERSION,
        'sequence': 1,
        'assets': {
            f'foundry-{VERSION}-{target}.zip': {
                'size': len(data),
                'sha256': hashlib.sha256(data).hexdigest(),
            } for target in PLATFORMS
        },
    }),
                        encoding='utf-8')
    key = root / 'key'
    trust = root / 'root.json'
    install_manifest = assets / 'install-manifest.txt'
    sig = assets / 'install-manifest.txt.sig'
    signers = root / 'allowed_signers'
    subprocess.run([
        release, 'keygen', '--private-output', key, '--root-output', trust,
        '--key-id', 'installer-test'
    ],
                   check=True)
    subprocess.run([
        release, 'sign-installer', '--input', manifest, '--manifest',
        install_manifest, '--output', sig, '--root', trust, '--allowed-signers',
        signers
    ],
                   env=dict(os.environ, FOUNDRY_SIGNING_KEY=key.read_text()),
                   check=True)
    cert = root / 'cert.pem'
    cert_key = root / 'tls-key.pem'
    subprocess.run([
        openssl, 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
        '-subj', '/CN=localhost', '-addext', 'subjectAltName=IP:127.0.0.1',
        '-out', cert, '-keyout', cert_key
    ],
                   check=True,
                   capture_output=True)

    def handler(*args, **kwargs):
        return QuietHandler(*args, directory=www, **kwargs)

    with ThreadingHTTPServer(('127.0.0.1', 0), handler) as server:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, cert_key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            subprocess.run(
                ['node', ROOT / 'website/scripts/build-installers.mjs', www],
                check=True)
            origin = f'https://127.0.0.1:{server.server_port}'
            if windows:
                command = [
                    'pwsh', '-NoProfile', '-NonInteractive', '-File',
                    www / 'install.ps1'
                ]
                installer = None
            else:
                command = ['sh', '-s', '--']
                installer = subprocess.check_output(
                    ['curl', '-fsSL', '--cacert', cert, f'{origin}/install.sh'],
                    timeout=30)
            env = dict(os.environ, FOUNDRY_CA_CERT=str(cert))

            def install(name,
                        error=None,
                        allowed_signers=signers,
                        version=None,
                        existing=False):
                destination = root / name
                url = f'{origin}/releases'
                if windows:
                    options = [
                        '-ReleaseBaseUrl', url, '-AllowedSigners',
                        allowed_signers, '-InstallDir', destination
                    ]
                    if version:
                        options += ['-Version', version]
                else:
                    options = [
                        '--release-base-url', url, '--allowed-signers',
                        allowed_signers, '--install-dir', destination
                    ]
                    if version:
                        options += ['--version', version]
                result = subprocess.run(command + options,
                                        input=installer,
                                        capture_output=True,
                                        env=env,
                                        timeout=90)
                if error is not None:
                    assert result.returncode and error.encode(
                    ) in result.stderr, result
                    assert destination.exists() == existing
                    return
                assert result.returncode == 0, result
                assert {p.name for p in destination.iterdir()
                       } == {foundry, worker}
                subprocess.run([destination / foundry, '--version'], check=True)
                for name in (foundry, worker):
                    assert os.access(destination / name, os.X_OK)
                    assert (destination /
                            name).read_bytes() == (binaries /
                                                   name).read_bytes()

            install('installed client')
            install('installed client',
                    'install directory already exists',
                    existing=True)
            assert {p.name for p in (root / 'installed client').iterdir()
                   } == {foundry, worker}
            original = sig.read_bytes()
            sig.write_bytes(b'not a signature\n')
            install('bad signature', 'release signature verification failed')
            sig.write_bytes(original)
            original_manifest = install_manifest.read_bytes()
            install_manifest.write_bytes(original_manifest + b' ')
            install('bad manifest', 'release signature verification failed')
            install_manifest.write_bytes(original_manifest)
            unrelated_key = root / 'unrelated-key'
            unrelated_root = root / 'unrelated.json'
            unrelated_signers = root / 'unrelated-signers'
            subprocess.run([
                release,
                'keygen',
                '--private-output',
                unrelated_key,
                '--root-output',
                unrelated_root,
                '--key-id',
                'unrelated',
            ],
                           check=True)
            subprocess.run([
                release,
                'sign-installer',
                '--input',
                manifest,
                '--manifest',
                root / 'unrelated-manifest',
                '--output',
                root / 'unrelated.sig',
                '--root',
                unrelated_root,
                '--allowed-signers',
                unrelated_signers,
            ],
                           env=dict(
                               os.environ,
                               FOUNDRY_SIGNING_KEY=unrelated_key.read_text()),
                           check=True)
            install('wrong signer',
                    'release signature verification failed',
                    allowed_signers=unrelated_signers)
            expired_signers = root / 'expired-signers'
            expired_signers.write_text(
                '# foundry-install-v1 expires-at 1\n' +
                signers.read_text(encoding='utf-8').split('\n', 1)[1],
                encoding='utf-8')
            install('expired signer',
                    'invalid or expired allowed-signers file',
                    allowed_signers=expired_signers)
            with archive.open('r+b') as stream:
                stream.write(b'XX')
            install('bad archive', 'SHA-256 mismatch', version=VERSION)
            print(f'{platform}: installer verified valid and tampered releases')
        finally:
            server.shutdown()
            thread.join()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--openssl',
                        default=os.environ.get('FOUNDRY_OPENSSL', 'openssl'))
    options = parser.parse_args()
    openssl = shutil.which(options.openssl)
    if not openssl:
        parser.error('OpenSSL 3 is required for installer tests')
    with tempfile.TemporaryDirectory(
            prefix='foundry-install-test-') as directory:
        run_test(Path(directory), str(Path(openssl).resolve()))
