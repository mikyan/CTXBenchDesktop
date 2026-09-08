"""Resolve public image identities once, without changing dataset or task identities.

Non-empty company rules disable implicit registry fallback. Unmapped images may
still be used from the local engine (including imported application images).
"""
from __future__ import annotations

import re


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

    @property
    def restricted(self):
        return bool(self.rules)

    def resolve(self, reference):
        from .environments import image_reference
        image_reference(reference)
        # Content-addressed local images must never be rewritten or pulled.
        if reference.startswith("sha256:"):
            return reference
        rule = next((rule for rule in self.rules if reference.startswith(rule["source"])), None)
        return image_reference(rule["target"] + reference[len(rule["source"]):]) if rule else reference

    def may_pull(self, original):
        if self.environment.get("offline") or original.startswith("sha256:"):
            return False
        if not self.restricted:
            return True
        resolved = self.resolve(original)
        return any(resolved.startswith(rule["target"]) for rule in self.rules)

    def require_pull(self, original):
        if not self.may_pull(original):
            raise ValueError(f"Image is not installed and registry access is disabled for: {self.resolve(original)}. "
                             "Add a company image mapping or import the image into the selected Docker engine. No Docker Hub fallback was attempted.")
