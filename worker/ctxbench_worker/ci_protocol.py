"""The replaceable platform seam. No benchmark policy lives in an adapter.

Adapters prepare a frozen target, submit idempotently, poll that exact submission,
and retrieve optional reports. Errors are infrastructure failures, never FAIL.
"""
from typing import Protocol
import requests


class CIError(ValueError):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class ExplicitAuth(requests.auth.AuthBase):
    """Keep explicit headers (or no auth); never consult the operator's netrc."""
    def __call__(self, request):
        return request


class Platform(Protocol):
    def prepare(self, task) -> dict: ...
    def submit(self, target: dict, candidate: dict, receipt: dict, save) -> None: ...
    def poll(self, receipt: dict) -> dict: ...
    def report(self, receipt: dict, name: str) -> bytes: ...
    def cancel(self, receipt: dict) -> None: ...


class Transport:
    """Fixed authenticated origin, finite reads, no authenticated redirects/logs."""
    def __init__(self, root, token):
        self.root, self.token = root, token
        self.check = lambda: None

    def request(self, method, path, *, body=None, query=None, allowed=(200, 201, 202, 204), binary=False):
        self.check()
        if not path.startswith('/') or path.startswith('//') or '..' in path:
            raise CIError('CI: invalid adapter request path.')
        headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'CTXBench-CI/1',
                   'X-GitHub-Api-Version': '2022-11-28', 'Authorization': 'Bearer ' + self.token}
        try:
            with requests.request(method, self.root + path, json=body, params=query, headers=headers,
                                  auth=ExplicitAuth(), timeout=(10, 30), allow_redirects=False, stream=True) as response:
                if response.status_code not in allowed:
                    reason = 'authentication or permission denied' if response.status_code in {401, 403} else 'not found' if response.status_code == 404 else 'platform request failed'
                    raise CIError(f'CI: {reason} (HTTP {response.status_code}); check the connection and token permissions.', response.status_code)
                if response.status_code == 302:
                    # Artifact URLs are signed. Never persist them or forward API credentials.
                    return self.download(response.headers.get('Location', ''))
                if response.status_code == 204:
                    return {}
                content = self.read(response)
                if binary: return content
                import json
                return json.loads(content)
        except (requests.RequestException, ValueError) as error:
            if isinstance(error, CIError): raise
            raise CIError('CI: connection failed or returned invalid data. Check network, TLS certificates and platform compatibility.') from None

    @staticmethod
    def read(response):
        chunks, size = [], 0
        for chunk in response.iter_content(65536):
            size += len(chunk)
            if size > 16 * 1024 * 1024: raise CIError('CI: response exceeds the 16 MiB safety limit.')
            chunks.append(chunk)
        return b''.join(chunks)

    def download(self, url):
        from urllib.parse import urlsplit
        for _ in range(4):
            self.check()
            parsed = urlsplit(url)
            if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
                raise CIError('CI: artifact download requires an HTTPS address without embedded credentials.')
            with requests.get(url, auth=ExplicitAuth(), timeout=(10, 30), allow_redirects=False, stream=True) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    url = response.headers.get('Location', '')
                    continue
                if response.status_code != 200: raise CIError('CI: test report could not be downloaded.')
                return self.read(response)
        raise CIError('CI: too many artifact redirects.')
