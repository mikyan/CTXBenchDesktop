"""Real Docker metadata checks against an ephemeral local registry protocol fixture.

Run in the Worker image with --network host, the Docker socket and repository
mounted read-only at /source. No public registry, layer download or model call.
"""
import hashlib
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, '/source')
from worker.ctxbench_worker.standard_images import DockerImages

requests_seen = []


class Registry(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        requests_seen.append(self.path)
        status, media = 200, 'application/json'
        if self.path in {'/v2/', '/v2'}:
            body = {}
        elif '/missing/' in self.path:
            status, body = 404, {'errors': [{'code': 'MANIFEST_UNKNOWN', 'message': 'manifest unknown'}]}
        elif '/private/' in self.path:
            status, body = 401, {'errors': [{'code': 'UNAUTHORIZED', 'message': 'authentication required'}]}
        elif '/manifests/' in self.path:
            media = 'application/vnd.oci.image.index.v1+json'
            body = {'schemaVersion': 2, 'mediaType': media, 'manifests': [{
                'mediaType': 'application/vnd.oci.image.manifest.v1+json', 'digest': 'sha256:' + 'a' * 64, 'size': 123,
                'platform': {'os': 'linux', 'architecture': 'amd64'}}]}
        else:
            status, body = 404, {'errors': [{'code': 'NAME_UNKNOWN', 'message': 'name unknown'}]}
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header('Content-Type', media)
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Docker-Distribution-Api-Version', 'registry/2.0')
        self.send_header('Docker-Content-Digest', 'sha256:' + hashlib.sha256(raw).hexdigest())
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(raw)


def main():
    server = ThreadingHTTPServer(('127.0.0.1', 0), Registry)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host = f'localhost:{server.server_port}'
    try:
        with DockerImages() as images:
            before = {image.id for image in images.client.images.list()}
            actual = {name: images.availability(f'{host}/company/{name}:latest') for name in ('available', 'missing', 'private')}
            assert actual == {'available': 'available', 'missing': 'not-found', 'private': 'auth-required'}, actual
            assert before == {image.id for image in images.client.images.list()}, 'Metadata check must not install images'
            assert all(path.startswith('/v2') for path in requests_seen), requests_seen
            print(json.dumps({'statuses': actual, 'registryRequests': len(requests_seen), 'imagesChanged': 0, 'modelCalls': 0}))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


if __name__ == '__main__':
    main()
