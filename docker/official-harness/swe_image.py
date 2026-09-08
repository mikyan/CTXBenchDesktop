"""Adapt only v4's image namespace; leave upstream tests and scoring unchanged."""
import re
import uuid
from contextlib import contextmanager


@contextmanager
def swe_environment(instance_id, image_id):
    if not image_id:
        yield 'swebench'
        return
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', image_id) or not re.fullmatch(r'[A-Za-z0-9_-]+', instance_id):
        raise ValueError('SWE evaluation requires a frozen local image ID and a valid instance ID.')
    import docker
    namespace = 'ctxbench-eval-' + uuid.uuid4().hex
    repository = namespace + '/sweb.eval.x86_64.' + instance_id.replace('__', '_1776_').lower()
    client = docker.from_env()
    try:
        image = client.images.get(image_id)
        image.tag('ctxbench/frozen', image.id.replace(':', '-'))
        if not image.tag(repository, 'latest'):
            raise RuntimeError('Could not bind the frozen SWE evaluator image.')
        try:
            yield namespace
        finally:
            # Our unique alias only, not the public tag or any existing image.
            client.images.remove(repository + ':latest', noprune=True)
    finally:
        client.close()
