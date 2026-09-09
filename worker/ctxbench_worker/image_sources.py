"""Resolve public image identities once, without changing dataset or task identities.

Non-empty company rules disable implicit registry fallback. Unmapped images may
still be used from the local engine (including imported application images).
"""
from __future__ import annotations

import re


def exact_image_reference(value, *, target=False):
    """A reference, never a shell command. Full target names may include a digest."""
    from .environments import image_reference
    image_reference(value)
    if '://' in value or '//' in value or '..' in value or value.startswith('sha256:'):
        raise ValueError('Use a complete registry/repository image name, optionally with a tag or SHA-256 digest.')
    name = value.split('@', 1)[0]
    repository, colon, tag = name.rpartition(':')
    if colon and '/' not in tag:
        if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}', tag):
            raise ValueError('Invalid Docker image tag.')
        name = repository
    if not re.fullmatch(r'[a-z0-9][a-z0-9._:/-]*', name) or name.endswith('/'):
        raise ValueError('Use lowercase Docker repository paths and a valid image tag.')
    if target:
        host, slash, path = name.partition('/')
        if not slash or not path or not ('.' in host or ':' in host or host == 'localhost'):
            raise ValueError('Enter the complete image address including the registry hostname and repository path.')
    return value


def normalize_pull_reference(value):
    if not isinstance(value, str):
        raise ValueError('Enter one complete image address or docker pull command, without options or shell commands.')
    text = value.strip()
    if text.startswith('docker '):
        match = re.fullmatch(r'docker[ \t]+pull[ \t]+([^\s]+)', text)
        if not match:
            raise ValueError('Enter one complete image address or docker pull command, without options or shell commands.')
        text = match[1]
    return exact_image_reference(text, target=True)


def validate_overrides(rows):
    if not isinstance(rows, list) or len(rows) > 10000:
        raise ValueError('Provide at most 10,000 exact image addresses.')
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'source', 'target'}:
            raise ValueError('An exact image address needs source and target fields.')
        exact_image_reference(row['source'])
        exact_image_reference(row['target'], target=True)
        if row['source'] in seen:
            raise ValueError('Each official image can have only one exact download address.')
        seen.add(row['source'])
    return rows


def validate_mappings(rules):
    if not isinstance(rules, list) or len(rules) > 100:
        raise ValueError("Provide at most 100 Docker image prefix mappings.")
    seen = set()
    for rule in rules:
        if not isinstance(rule, dict) or set(rule) != {"source", "target"}:
            raise ValueError("An image mapping needs source and target prefixes.")
        for value in rule.values():
            if (not isinstance(value, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._:/-]{0,230}", value)
                    or "://" in value or ".." in value or "//" in value):
                raise ValueError("Use Docker prefixes without a protocol, credentials, spaces or placeholders.")
        host, separator, path = rule["target"].partition("/")
        if not separator or not path or not ("." in host or ":" in host or host == "localhost"):
            raise ValueError("Company image targets need an explicit registry hostname and repository path.")
        if host.split(":")[0] in {"docker.io", "index.docker.io", "registry-1.docker.io"}:
            raise ValueError("Company image targets must not point back to Docker Hub.")
        if rule["source"] in seen:
            raise ValueError("Each source image prefix can have only one target.")
        seen.add(rule["source"])
    return rules


class ImageSources:
    def __init__(self, environment=None):
        self.environment = environment or {}
        self.rules = sorted(validate_mappings(self.environment.get("imageMappings", [])),
                            key=lambda rule: len(rule["source"]), reverse=True)
        self.overrides = {row['source']: row['target'] for row in validate_overrides(self.environment.get('imageOverrides', []))}

    @property
    def restricted(self):
        return bool(self.rules or self.overrides)

    def resolve(self, reference):
        from .environments import image_reference
        image_reference(reference)
        # Content-addressed local images must never be rewritten or pulled.
        if reference.startswith("sha256:"):
            return reference
        if reference in self.overrides:
            return self.overrides[reference]
        rule = next((rule for rule in self.rules if reference.startswith(rule["source"])), None)
        return image_reference(rule["target"] + reference[len(rule["source"]):]) if rule else reference

    def may_pull(self, original):
        if self.environment.get("offline") or original.startswith("sha256:"):
            return False
        if not self.restricted:
            return True
        resolved = self.resolve(original)
        return resolved in self.overrides.values() or any(resolved.startswith(rule["target"]) for rule in self.rules)

    def require_pull(self, original):
        if not self.may_pull(original):
            raise ValueError(f"Image is not installed and registry access is disabled for: {self.resolve(original)}. "
                             "Add a company image mapping or import the image into the selected Docker engine. No Docker Hub fallback was attempted.")
