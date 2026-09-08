"""Versioned, non-secret company settings. Applying a profile never mutates a run."""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from .agent_args import normalize_agent_args
from .catalog import fingerprint
from .database import utc_now
from .runner import ENV_NAME


def public_material(value, redact):
    """Reject credentials before persistence; errors deliberately never echo input."""
    if isinstance(value, str):
        if redact(value) != value or "\0" in value or re.search(
            r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
            r"https?://[^\s/]*@|(?:api[_-]?key|password|secret|token)\s*[=:]\s*['\"]?(?!\$|\{|<)[a-zA-Z0-9_/+.-]{12,}", value, re.I
        ):
            raise ValueError("Credentials are not allowed in shared configuration or resources.")
    elif isinstance(value, dict):
        for key, child in value.items():
            public_material(key, redact)
            public_material(child, redact)
    elif isinstance(value, list):
        for child in value:
            public_material(child, redact)


def image_reference(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/@-]{0,255}", value):
        raise ValueError("Provide a local Docker image reference without credentials or whitespace.")
    if "@" in value and not re.fullmatch(r"[^@]+@sha256:[0-9a-f]{64}", value):
        raise ValueError("Image references must not embed credentials; only SHA-256 digest suffixes may follow @.")
    return value


def validate_profile(value, redact=lambda text: text):
    fields = {"format", "version", "name", "agentImage", "harnessImage", "provider", "model",
              "envNames", "agentArgs", "offline", "gitMirrors", "providerDomains"}
    if not isinstance(value, dict) or not fields <= set(value) or set(value) - fields - {"imageMappings"} or value.get("format") != "ctxbench-company-profile" or value.get("version") != 1:
        raise ValueError("Unsupported company profile format or fields.")
    public_material(value, redact)
    from .image_sources import validate_mappings
    validate_mappings(value.get("imageMappings", []))
    for key in ("name", "provider", "model"):
        if not isinstance(value[key], str) or not 1 <= len(value[key].strip()) <= 160:
            raise ValueError("Company name, provider and model are required (maximum 160 characters).")
    for key in ("agentImage", "harnessImage"):
        image_reference(value[key])
    if type(value["offline"]) is not bool:
        raise ValueError("Offline preparation must be a boolean.")
    names = value["envNames"]
    if not isinstance(names, list) or len(names) > 100 or not all(isinstance(n, str) and ENV_NAME.fullmatch(n) for n in names) or len(set(names)) != len(names):
        raise ValueError("Provide unique environment variable names, never their values.")
    normalize_agent_args(value["agentArgs"])
    mirrors = value["gitMirrors"]
    if not isinstance(mirrors, list) or len(mirrors) > 100:
        raise ValueError("Provide at most 100 exact repository mirrors.")
    origins = set()
    for mirror in mirrors:
        if not isinstance(mirror, dict) or set(mirror) != {"repository", "mirror"}:
            raise ValueError("A Git mirror needs repository and mirror URLs.")
        for url in mirror.values():
            if not isinstance(url, str) or not url or url.startswith("-"):
                raise ValueError("Invalid Git mirror location.")
            parsed = urlsplit(url)
            if parsed.password or parsed.query or parsed.fragment or (parsed.username and parsed.scheme != "ssh") or parsed.scheme not in {"https", "ssh", "git", ""}:
                raise ValueError("Use a credential-free HTTPS/SSH Git URL or absolute Worker path.")
            if not parsed.scheme and not url.startswith("/"):
                raise ValueError("Local mirrors must use an absolute Worker path.")
        if mirror["repository"] in origins:
            raise ValueError("Each source repository can have only one mirror.")
        origins.add(mirror["repository"])
    domains = value["providerDomains"]
    if not isinstance(domains, list) or len(domains) > 100 or not all(isinstance(d, str) and re.fullmatch(r"\.?[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?", d) and ".." not in d for d in domains):
        raise ValueError("Provider domains must be hostnames, without protocol, port or path.")
    return value


def public_image_config(config, redact):
    public_material(config, redact)
    for item in config.get("Env", []) or []:
        name, _, value = item.partition("=")
        if value and re.search(r"(?:^|_)(?:API_KEY|TOKEN|PASSWORD|SECRET|PRIVATE_KEY|ACCESS_KEY)(?:_|$)", name, re.I):
            raise ValueError("Image configuration contains a credential-bearing environment variable. Rebuild without credentials.")


class EnvironmentProfiles:
    def __init__(self, database, redact):
        self.db, self.redact = database, redact

    def save(self, value):
        document = validate_profile(value, self.redact)
        key = fingerprint(document)
        try:
            return self.get(key)
        except KeyError:
            record = {"id": key, "createdAt": utc_now(), "document": document}
            self.db.put_document("companyProfiles", key, record)
            return record

    def get(self, key):
        record = self.db.get_document("companyProfiles", key)
        if fingerprint(validate_profile(record["document"], self.redact)) != key:
            raise ValueError("Company profile was modified; save a new version.")
        return record

    def list(self):
        return [self.get(row["id"]) for row in self.db.list_documents("companyProfiles")]

    def proxy_config(self, key):
        domains = self.get(key)["document"]["providerDomains"]
        if not domains:
            raise ValueError("Add at least one provider domain before exporting proxy rules.")
        return "\n".join(["http_port 3128", "visible_hostname ctxbench-egress-proxy", "acl SSL_ports port 443",
                          "acl CONNECT method CONNECT", "acl provider_domains dstdomain " + " ".join(domains),
                          "http_access deny !SSL_ports", "http_access allow CONNECT provider_domains",
                          "http_access deny all", "access_log none", "cache deny all", ""])
