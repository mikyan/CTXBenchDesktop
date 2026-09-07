"""Frozen argv, never shell source or a credential transport."""
from __future__ import annotations

import hashlib
import json
import re

_CREDENTIAL_FLAG = re.compile(r'^--?(?:api[-_]?key|(?:access[-_]?|auth[-_]?|bearer[-_]?)?token|password|secret|client[-_]?secret|credential)s?(?:=|$)', re.I)
PI_SWITCHES = frozenset({'--verbose', '--no-tools', '-nt', '--no-builtin-tools', '-nbt', '--no-themes', '--no-context-files', '-nc'})
PI_VALUES = frozenset({'--tools', '-t', '--exclude-tools', '-xt'})


def normalize_agent_args(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)) or len(value) > 128:
        raise ValueError('Agent startup arguments must be an array of at most 128 strings.')
    if any(not isinstance(arg, str) or len(arg) > 4096 or
           any(ord(char) < 32 or 127 <= ord(char) <= 159 or 0xD800 <= ord(char) <= 0xDFFF for char in arg) for arg in value):
        raise ValueError('Each agent argument must be text of at most 4096 characters without control characters.')
    if sum(map(len, value)) > 32768:
        raise ValueError('Agent startup arguments must total at most 32768 characters.')
    if any(_CREDENTIAL_FLAG.match(arg) for arg in value):
        raise ValueError('Pass credentials through selected environment variables, not agent startup arguments.')
    return tuple(value)


def validate_pi_args(value: object) -> tuple[str, ...]:
    args = normalize_agent_args(value)
    index = 0
    while index < len(args):
        arg = args[index]
        if arg in PI_VALUES:
            index += 1
            if index >= len(args) or not args[index].strip() or args[index].startswith(('-', '@')):
                raise ValueError('Pi tool options require a separate, non-empty tool-list argument.')
        elif arg not in PI_SWITCHES:
            raise ValueError('Unsupported Pi startup argument. Use --tools, --exclude-tools, --no-tools, --no-builtin-tools, --no-themes, --no-context-files or --verbose. Model, prompt, RPC, session and discovery settings are controlled by the benchmark.')
        index += 1
    return args


def agent_args_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(normalize_agent_args(value), ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def verify_agent_args_receipt(metadata: dict, args: object) -> None:
    if args and (metadata.get('agentArgsProtocolVersion') != 1 or metadata.get('agentArgsHash') != agent_args_hash(args)):
        raise ValueError('Agent did not confirm the configured startup arguments; refusing an ignored or modified configuration.')
