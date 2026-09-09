"""Public, immutable CI configuration. Credentials never belong in these records."""
import re
from urllib.parse import urlsplit


def ci_test(value):
    if not isinstance(value, dict) or set(value) - {'connectionId', 'requiredJobs', 'reportArtifact', 'minTests', 'timeoutMinutes', 'allowRemoteExecution'}:
        raise ValueError('CI: unsupported grading configuration.')
    if not re.fullmatch(r'[a-f0-9]{64}', str(value.get('connectionId', ''))):
        raise ValueError('CI: select a saved platform connection.')
    jobs = value.get('requiredJobs')
    if not isinstance(jobs, list) or not 1 <= len(jobs) <= 100 or len(set(map(str, jobs))) != len(jobs) or any(not isinstance(j, str) or not j.strip() or len(j) > 200 or any(c in j for c in '\r\n\0') for j in jobs):
        raise ValueError('CI: specify unique required job names, one per line.')
    artifact = value.get('reportArtifact', '')
    if not isinstance(artifact, str) or len(artifact) > 200 or any(c in artifact for c in '\r\n\0'):
        raise ValueError('CI: invalid JUnit artifact name.')
    for key, default, limit in [('minTests', 1, 1_000_000), ('timeoutMinutes', 30, 1440)]:
        number = value.get(key, default)
        if type(number) is not int or not 1 <= number <= limit:
            raise ValueError('CI: test minimum and timeout must be positive integers within their limits.')
    if value.get('allowRemoteExecution') is not True:
        raise ValueError('CI: acknowledge uploading candidate code and triggering remote workflows.')
    return {**value, 'reportArtifact': artifact, 'minTests': value.get('minTests', 1), 'timeoutMinutes': value.get('timeoutMinutes', 30)}


def ci_connection(value):
    if not isinstance(value, dict) or set(value) != {'name', 'provider', 'apiUrl', 'repository', 'workflow'}:
        raise ValueError('CI: a connection needs name, provider, API URL, repository and workflow.')
    if any(not isinstance(v, str) or not v.strip() or len(v) > 500 or any(c in v for c in '\r\n\0') for v in value.values()):
        raise ValueError('CI: connection fields must be nonempty text without credentials.')
    if value['provider'] not in {'github-actions', 'http-ci'}:
        raise ValueError('CI: unsupported platform adapter.')
    url = urlsplit(value['apiUrl'])
    if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment or '..' in url.path:
        raise ValueError('CI: use an HTTPS API URL without credentials, query or fragment.')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', value['repository']):
        raise ValueError('CI: repository must use owner/name format.')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', value['workflow']) or value['workflow'] in {'.', '..'}:
        raise ValueError('CI: enter a workflow filename or pipeline ID, not a path.')
    return {**value, 'apiUrl': value['apiUrl'].rstrip('/')}
