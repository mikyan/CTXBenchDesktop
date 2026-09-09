"""A custom coding command is frozen with the case, not confused with grading."""
from __future__ import annotations
import re


def command_agent(value):
    if value is None:
        return None
    from .environments import image_reference, public_material
    if not isinstance(value, dict) or set(value) != {'image', 'command'}:
        raise ValueError('Custom Agent requires an image and a command argument array.')
    image_reference(value['image'])
    command = value['command']
    if (not isinstance(command, (list, tuple)) or not 1 <= len(command) <= 128
            or any(not isinstance(arg, str) or '\0' in arg or len(arg) > 20000 for arg in command)
            or not command[0].strip() or sum(map(len, command)) > 32768):
        raise ValueError('Custom Agent command must be a nonempty argument array, at most 32768 characters.')
    normalized = {'image': value['image'], 'command': list(command)}
    public_material(normalized, lambda text: text)
    if re.search(r"--?(?:api[-_]?key|(?:access[-_]?|auth[-_]?)?token|password|secret)[\"']?(?:=|\s+)[\"']?(?!\$|\{|<)[A-Za-z0-9_/+.-]+", ' '.join(command), re.I):
        raise ValueError('Use runtime environment variables instead of credential literals in Agent commands.')
    return normalized
