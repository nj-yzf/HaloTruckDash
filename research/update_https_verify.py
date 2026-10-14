"""Run a real HTTPS release check/download against an ephemeral loopback server."""
import functools
import hashlib
import http.server
import io
import json
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from halo_dashboard.updates import FORMAT, fetch_release, download_release

openssl = shutil.which('openssl')
if not openssl:
    git = shutil.which('git')
    candidate = Path(git).parent.parent / 'usr' / 'bin' / 'openssl.exe' if git else Path('missing')
    if candidate.is_file():
        openssl = str(candidate)
if not openssl:
    raise RuntimeError('This developer HTTPS check needs OpenSSL; the shipped app does not.')

with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent) as temporary:
    directory = Path(temporary)
    cert, key = directory / 'localhost.pem', directory / 'localhost-key.pem'
    subprocess.run([openssl, 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', str(key),
                    '-out', str(cert), '-days', '1', '-subj', '/CN=localhost',
                    '-addext', 'subjectAltName=DNS:localhost,IP:127.0.0.1'], check=True, capture_output=True)
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as package:
        package.writestr('HaloTruckDash.exe', b'MZ loopback integration test')
    content = output.getvalue()
    (directory / 'test.zip').write_bytes(content)
    document = {'format': FORMAT, 'schema': 1, 'version': '0.6.0', 'notes': '真实HTTPS检查及下载测试',
                'windows_x64': {'url': '../test.zip', 'size': len(content), 'sha256': hashlib.sha256(content).hexdigest()}}
    (directory / 'v0.6.0').mkdir()
    (directory / 'v0.6.0' / 'latest.json').write_text(json.dumps(document), encoding='utf-8')
    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/latest.json':
                self.send_response(302)
                self.send_header('Location', '/v0.6.0/latest.json')
                self.end_headers()
            elif self.path == '/downgrade':
                self.send_response(302)
                self.send_header('Location', 'http://127.0.0.1:1/must-not-request')
                self.end_headers()
            else:
                super().do_GET()
        def log_message(self, *args):
            pass
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=str(directory)))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        # Trust only this temporary CA in this test process. Production uses the
        # standard certificate store, with no verification bypass or CA install.
        with patch.dict(os.environ, {'SSL_CERT_FILE': str(cert), 'NO_PROXY': 'localhost,127.0.0.1'}):
            base = f'https://localhost:{server.server_port}'
            release = fetch_release(base + '/latest.json')
            assert release.url == base + '/test.zip' and release.version == '0.6.0'
            downloaded = download_release(release, directory / 'downloads')
            assert downloaded.read_bytes() == content
            try:
                fetch_release(base + '/downgrade')
            except ValueError:
                pass
            else:
                raise AssertionError('HTTPS to HTTP redirect was allowed')
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
print('Real HTTPS redirect, release manifest, relative download, SHA256/ZIP checks and HTTP downgrade rejection passed.')
