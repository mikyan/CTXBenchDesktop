import json
import runpy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import docker
import requests

from worker.ctxbench_worker.catalog import fingerprint
from worker.ctxbench_worker.environments import validate_profile
from worker.ctxbench_worker.image_sources import ImageSources, validate_mappings
from worker.ctxbench_worker.runtime import Runtime
from worker.ctxbench_worker.standard_images import DockerImages
from worker.tests.test_intranet import profile

RULE = {'source': 'swebench/sweb.eval.x86_64.', 'target': 'registry.company.example/swe-bench-verifield/'}
ORIGINAL = 'swebench/sweb.eval.x86_64.sympy_1776_sympy-18189:latest'
TARGET = 'registry.company.example/swe-bench-verifield/sympy_1776_sympy-18189:latest'
IMAGE = 'sha256:' + 'a' * 64
ROOT = Path(__file__).resolve().parents[2]


class ImageSourceTests(unittest.TestCase):
    def test_company_example_and_longest_prefix_keep_actual_spelling(self):
        source = ImageSources({'imageMappings': [RULE]})
        self.assertEqual(source.resolve(ORIGINAL), TARGET)
        self.assertTrue(source.may_pull(ORIGINAL))
        self.assertFalse(source.may_pull('tgloaguen/planbenchx86_opshin_opshin:latest'))
        exact = {'source': ORIGINAL, 'target': 'other.company.example/special/fix:v2'}
        self.assertEqual(ImageSources({'imageMappings': [RULE, exact]}).resolve(ORIGINAL), exact['target'])
        self.assertEqual(source.resolve(TARGET), TARGET)
        self.assertTrue(source.may_pull(TARGET))
        self.assertEqual(source.resolve(IMAGE), IMAGE)
        self.assertFalse(source.may_pull(IMAGE))

    def test_offline_and_no_profile_behavior(self):
        self.assertTrue(ImageSources().may_pull(ORIGINAL))
        source = ImageSources({'offline': True, 'imageMappings': [RULE]})
        self.assertEqual(source.resolve(ORIGINAL), TARGET)
        self.assertFalse(source.may_pull(ORIGINAL))

    def test_reject_ambiguous_rules_credentials_placeholders_and_public_fallback(self):
        bad = [None, 'mapping', [RULE, RULE], [{**RULE, 'extra': True}]]
        bad += [[{**RULE, 'target': target}] for target in ('https://registry.example/path/', 'user:password@registry.example/path/',
                   '{domain}/swe-bench-verifield/', 'docker.io/swebench/', 'library/image', 'registry.example/a/../b/', 'registry.example/a b')]
        for rules in bad:
            with self.subTest(rules=rules), self.assertRaises(ValueError): validate_mappings(rules)

    def test_old_profile_fingerprint_is_unchanged_and_new_rules_are_frozen(self):
        old = profile()
        before = json.dumps(old, sort_keys=True)
        self.assertEqual(fingerprint(validate_profile(old)), fingerprint(json.loads(before)))
        self.assertEqual(json.dumps(old, sort_keys=True), before)
        self.assertNotEqual(fingerprint(validate_profile({**old, 'imageMappings': [RULE]})), fingerprint(old))

    def test_runtime_ignores_cached_public_alias_and_only_pulls_company_name(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Runtime(Path(directory), Mock())
            client = Mock()
            image = SimpleNamespace(id=IMAGE, tag=Mock())
            client.images.get.side_effect = [docker.errors.ImageNotFound('missing'), image]
            client.api.pull.return_value = iter([{'status': 'Pull complete'}])
            with patch('docker.from_env', return_value=client), runtime.using_environment({'imageMappings': [RULE]}):
                self.assertEqual(runtime.resolve_image(ORIGINAL), IMAGE)
            self.assertEqual([call.args for call in client.images.get.call_args_list], [(TARGET,), (TARGET,)])
            client.api.pull.assert_called_once_with(TARGET, stream=True, decode=True)

    def test_missing_unmapped_and_frozen_images_never_pull_or_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Runtime(Path(directory), Mock())
            client = Mock()
            client.images.get.side_effect = docker.errors.ImageNotFound('missing')
            with patch('docker.from_env', return_value=client), runtime.using_environment({'imageMappings': [RULE]}):
                with self.assertRaisesRegex(ValueError, 'No Docker Hub fallback'):
                    runtime.resolve_image('tgloaguen/ctxbench:latest')
                runtime.pin_images({ORIGINAL: IMAGE})
                with self.assertRaisesRegex(ValueError, 'frozen local image'):
                    runtime.resolve_image(ORIGINAL)
            client.images.pull.assert_not_called()
            self.assertEqual(runtime.environment, {})
            self.assertEqual(runtime._environment.image_pins, {})

    def test_local_unmapped_application_image_is_reusable(self):
        with tempfile.TemporaryDirectory() as directory:
            client = Mock()
            client.images.get.return_value = SimpleNamespace(id=IMAGE, tag=Mock())
            runtime = Runtime(Path(directory), Mock())
            with patch('docker.from_env', return_value=client), runtime.using_environment({'imageMappings': [RULE]}):
                self.assertEqual(runtime.resolve_image('ctxbench/agent-pi:0.1.0'), IMAGE)
            client.images.pull.assert_not_called()

    def test_old_harness_fails_with_upgrade_guidance_before_use(self):
        with tempfile.TemporaryDirectory() as directory:
            client = Mock(); client.images.get.return_value.labels = {}
            runtime = Runtime(Path(directory), Mock())
            with patch('docker.from_env', return_value=client), runtime.using_environment({'imageMappings': [RULE]}):
                with self.assertRaisesRegex(ValueError, 'updated official harness'):
                    runtime.require_image_source_harness(IMAGE)
                client.images.get.return_value.labels = {'io.ctxbench.image-sources': '1'}
                runtime.require_image_source_harness(IMAGE)
            self.assertEqual(client.close.call_count, 2)

    def test_registry_status_does_not_confuse_missing_auth_or_network(self):
        store = DockerImages(); store.client = Mock()
        for code, explanation, expected in [(404, 'manifest unknown', 'not-found'), (401, 'unauthorized', 'auth-required'),
                  (500, 'denied PRIVATE_AUTH_DATA', 'auth-required'), (500, 'context deadline exceeded', 'unreachable')]:
            response = requests.Response(); response.status_code = code
            store.client.images.get_registry_data.side_effect = docker.errors.APIError('request failed', response=response, explanation=explanation)
            self.assertEqual(store.availability(TARGET), expected)
        store.client.images.get_registry_data.side_effect = requests.exceptions.Timeout('PRIVATE_DATA')
        self.assertEqual(store.availability(TARGET), 'unreachable')
        store.client.images.get_registry_data.side_effect = None
        for supported, status in [(True, 'available'), (False, 'wrong-platform')]:
            store.client.images.get_registry_data.return_value.has_platform.return_value = supported
            self.assertEqual(store.availability(TARGET), status)
        store.client.images.pull.assert_not_called()

    def test_swe_alias_is_local_unique_and_cleaned_without_overwriting_public_tags(self):
        module = runpy.run_path(str(ROOT / 'docker/official-harness/swe_image.py'))
        client = Mock(); client.__enter__ = Mock(return_value=client); client.__exit__ = Mock(return_value=False)
        image = SimpleNamespace(id=IMAGE, tag=Mock(return_value=True))
        client.images.get.return_value = image
        with patch('docker.from_env', return_value=client):
            with module['swe_environment']('sympy__sympy-18189', None) as namespace:
                self.assertEqual(namespace, 'swebench')
            with self.assertRaisesRegex(RuntimeError, 'fixture'):
                with module['swe_environment']('sympy__sympy-18189', IMAGE) as namespace:
                    self.assertTrue(namespace.startswith('ctxbench-eval-'))
                    raise RuntimeError('fixture')
        client.images.get.assert_called_once_with(IMAGE)
        client.images.pull.assert_not_called()
        client.images.remove.assert_called_once_with(namespace + '/sweb.eval.x86_64.sympy_1776_sympy-18189:latest', noprune=True)

    def test_ctx_source_override_never_pulls_the_dataset_image(self):
        module = runpy.run_path(str(ROOT / 'docker/official-harness/agentbench_environment.py'))
        client = Mock(); client.images.get.side_effect = docker.errors.ImageNotFound('missing')
        with tempfile.TemporaryDirectory() as directory, patch('docker.from_env', return_value=client):
            with self.assertRaisesRegex(ValueError, 'fallback is disabled'):
                module['prepare_environment']({'docker_image': 'tgloaguen/original:v1'}, Path(directory), IMAGE)
        client.images.get.assert_called_once_with(IMAGE)
        client.images.pull.assert_not_called()
