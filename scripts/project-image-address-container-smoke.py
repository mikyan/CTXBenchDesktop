"""Real local-registry pull, without external downloads or production changes.

Run in the existing worker image using --network host, /source read-only,
Docker socket and a fresh /tmp/ctxbench-image-address-... directory as argv[1].
Serves only the already installed public hello-world image on ephemeral loopback.
No Agent calls, real benchmark scoring, or application image rebuilds.
"""
import gzip
import hashlib
import io
import json
import os
import ssl
import subprocess
import sys
import tarfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import docker

sys.path.insert(0, '/source/worker')
os.environ['PYTHONPATH'] = '/source/worker'
# The existing image may contain older source in /app; -m subprocesses must
# import this read-only checkout too, not the old working-directory package.
os.chdir('/source/worker')
from ctxbench_worker.engine import create_engine_from_environment
from ctxbench_worker.intranet import IntranetWorkbench
from ctxbench_worker.standard_images import swe_image
from ctxbench_worker.workbench import Workbench

root = Path(sys.argv[1]).resolve()
assert root.parent == Path('/tmp') and root.name.startswith('ctxbench-image-address-')
assert root.is_dir() and not list(root.iterdir()), 'Use a fresh isolated directory'
os.environ['CTXBENCH_HOST_DATA_DIR'] = str(root)
client = docker.from_env()
original = client.images.get('hello-world:latest')
blob = b''.join(original.save())
blobs = {}
def descriptor(content, media):
    digest = 'sha256:' + hashlib.sha256(content).hexdigest()
    blobs[digest] = content
    return {'mediaType': media, 'size': len(content), 'digest': digest}
with tarfile.open(fileobj=io.BytesIO(blob)) as archive:
    saved = json.load(archive.extractfile('manifest.json'))[0]
    config = archive.extractfile(saved['Config']).read()
    layers = [archive.extractfile(name).read() for name in saved['Layers']]
manifest = json.dumps({'schemaVersion': 2, 'mediaType': 'application/vnd.docker.distribution.manifest.v2+json',
    'config': descriptor(config, 'application/vnd.docker.container.image.v1+json'),
    'layers': [descriptor(gzip.compress(layer, mtime=0), 'application/vnd.docker.image.rootfs.diff.tar.gzip') for layer in layers]}).encode()
manifest_digest = 'sha256:' + hashlib.sha256(manifest).hexdigest()
observed = []
class Registry(BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def do_GET(self): self.serve(True)
    def do_HEAD(self): self.serve(False)
    def serve(self, body):
        observed.append(self.path)
        data, media, digest = None, 'application/json', None
        if self.path.rstrip('/') == '/v2': data = b'{}'
        elif '/manifests/' in self.path:
            data, media, digest = manifest, 'application/vnd.docker.distribution.manifest.v2+json', manifest_digest
        elif '/blobs/' in self.path:
            digest = self.path.rsplit('/', 1)[-1]
            data, media = blobs.get(digest), 'application/octet-stream'
        self.send_response(200 if data is not None else 404)
        self.send_header('Content-Type', media)
        self.send_header('Docker-Distribution-API-Version', 'registry/2.0')
        if digest: self.send_header('Docker-Content-Digest', digest)
        self.send_header('Content-Length', str(len(data or b'')))
        self.end_headers()
        if body and data: self.wfile.write(data)

server = ThreadingHTTPServer(('127.0.0.1', 0), Registry)
# The containerd image store expects HTTPS even for loopback registries. Its
# loopback policy accepts this ephemeral self-signed certificate; do not alter
# daemon settings or the system trust store for the test.
subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
    '-keyout', str(root / 'registry.key'), '-out', str(root / 'registry.crt'),
    '-subj', '/CN=localhost', '-addext', 'subjectAltName=IP:127.0.0.1,DNS:localhost', '-days', '1'],
    check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
tls.load_cert_chain(root / 'registry.crt', root / 'registry.key')
server.socket = tls.wrap_socket(server.socket, server_side=True)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
target = f'127.0.0.1:{server.server_port}/{root.name.lower()}/planbenchx86:latest'
target_was_absent = False
new_frozen_alias = None
try:
    try: client.images.get(target)
    except docker.errors.ImageNotFound: target_was_absent = True
    else: raise AssertionError('Test tag already exists; refusing to modify it')
    engine = create_engine_from_environment(root, 'docker')
    wb = Workbench(engine, None)
    operator = IntranetWorkbench(wb)
    ctx_source = 'fixture/planbenchx86:latest'
    ctx = wb.catalog.register('CTX address fixture', 'ctxbench', [{'instance_id': 'fixture-1',
        'base_repo': 'fixture/repo', 'base_sha': 'a' * 40, 'docker_image': ctx_source,
        'problem_description': 'Infrastructure fixture only, not a runnable benchmark.'}])['id']
    swe_instance = 'fixture__repo-1'
    swe_source = swe_image(swe_instance)
    swe = wb.catalog.register('SWE address fixture', 'swebench', [{'instance_id': swe_instance,
        'repo': 'fixture/repo', 'base_commit': 'a' * 40, 'problem_statement': 'Image transport fixture only.'}])['id']
    for revision, (dataset, source) in enumerate([(ctx, ctx_source), (swe, swe_source)]):
        wb.image_sources.save(dataset, {'expectedRevision': revision,
            'overrides': [{'source': source, 'target': 'docker pull ' + target}]})
    operation = operator.enqueue('standard-images', {'dataset': ctx, 'taskIds': ['fixture-1'], 'confirmed': True, 'imageSourcesRevision': 2})
    wb.image_sources.save(ctx, {'expectedRevision': 2, 'overrides': [{'source': ctx_source,
        'target': target.replace('/planbenchx86:', '/future-image:')}]})
    try:
        result = operator.execute(operation)
    except ValueError:
        # This fixture contains no credentials or real registry data. Expose its
        # local protocol diagnostics when the production helper sanitizes errors.
        print(json.dumps({'registryRequests': observed, 'progress': operator.status(operation['id']).get('progress')}), flush=True)
        try:
            for event in client.api.pull(target, stream=True, decode=True, platform='linux/amd64'):
                if event.get('error'): print(event['error'], flush=True)
        except docker.errors.DockerException as error:
            print(str(error), flush=True)
        raise
    assert result['images'][0]['cached'] is False
    assert result['images'][0]['reference'] == target
    downloaded = client.images.get(target)
    assert result['images'][0]['imageId'] == downloaded.id
    # Containerd can expose the manifest ID instead of the image config ID.
    # Repacking an index as a single-platform manifest must preserve content.
    assert downloaded.attrs['RootFS']['Layers'] == original.attrs['RootFS']['Layers']
    assert downloaded.attrs['Config'] == original.attrs['Config']
    assert any('/manifests/' in path for path in observed), 'Expected a real Docker registry request'
    assert not any('/future-image/' in path for path in observed)
    frozen_alias = 'ctxbench/frozen:' + downloaded.id.replace(':', '-')
    try: client.images.get(frozen_alias)
    except docker.errors.ImageNotFound: new_frozen_alias = frozen_alias
    with wb.runtime.using_environment(operation['payload']['environment']):
        assert wb.runtime.resolve_image(ctx_source) == downloaded.id
    sw_op = operator.enqueue('standard-images', {'dataset': swe, 'taskIds': [swe_instance], 'confirmed': True})
    sw_result = operator.execute(sw_op)
    assert sw_result['images'][0]['cached'] is True
    assert sw_result['images'][0]['reference'] == target
    summary = {'status': 'passed', 'realDockerPull': True, 'registry': 'isolated ephemeral loopback',
        'downloadAddress': target, 'actualImageId': downloaded.id, 'ctxDownloaded': True, 'sweReusedSameTarget': True,
        'queuedAddressFrozen': True, 'runtimeResolvedSameImage': True, 'modelCalls': 0, 'externalDownloads': 0}
    (root / 'summary.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2), flush=True)
finally:
    server.shutdown(); thread.join(timeout=2); server.server_close()
    # Remove only our freshly-created alias, not layers or pre-existing tags.
    try:
        expected_ids = {original.id, manifest_digest, 'sha256:' + hashlib.sha256(config).hexdigest()}
        if new_frozen_alias and client.images.get(new_frozen_alias).id in expected_ids:
            client.images.remove(new_frozen_alias, noprune=True)
    except docker.errors.ImageNotFound: pass
    try:
        if target_was_absent and client.images.get(target).id in expected_ids:
            client.images.remove(target, noprune=True)
    except docker.errors.ImageNotFound: pass
    assert client.images.get('hello-world:latest').id == original.id
    client.close()
    (root / 'registry.key').unlink()
    (root / 'registry.crt').unlink()
