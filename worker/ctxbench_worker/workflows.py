"""Frozen, task-blind workflow configuration shared by planning and the container contract."""
from __future__ import annotations


def normalize_workflow(value: object) -> dict:
    if value is None or value == {}:
        return {}
    if not isinstance(value, dict) or set(value) - {'setupCommands', 'steps'}:
        raise ValueError('Invalid agent workflow configuration.')
    commands = value.get('setupCommands', [])
    steps = value.get('steps', [{'name': '', 'prompt': None}])
    if not isinstance(commands, list) or len(commands) > 20:
        raise ValueError('A workflow supports up to 20 startup commands.')
    if any(not isinstance(command, str) or not command.strip() or len(command) > 20000 or '\0' in command for command in commands):
        raise ValueError('Startup commands must be non-empty text without NUL characters.')
    if not isinstance(steps, list) or not 1 <= len(steps) <= 50:
        raise ValueError('A workflow requires between 1 and 50 prompt steps.')
    normalized = []
    for step in steps:
        if not isinstance(step, dict) or set(step) - {'name', 'prompt'}:
            raise ValueError('Invalid workflow step.')
        name, prompt = step.get('name', ''), step.get('prompt')
        if not isinstance(name, str) or len(name) > 120 or '\0' in name:
            raise ValueError('Step names must be text of at most 120 characters.')
        if prompt is not None and (not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 100000 or '\0' in prompt):
            raise ValueError('Custom step prompts must be non-empty text without NUL characters.')
        normalized.append({'name': name, 'prompt': prompt})
    if not commands and normalized == [{'name': '', 'prompt': None}]:
        return {}
    return {'setupCommands': list(commands), 'steps': normalized}


def workflow_request(value: object, default_prompt: str) -> dict | None:
    workflow = normalize_workflow(value)
    if not workflow:
        return None
    return {'version': 1, 'setupCommands': workflow['setupCommands'], 'steps': [
        {'name': step['name'], 'prompt': default_prompt if step['prompt'] is None else step['prompt'].replace('{{default_prompt}}', default_prompt)}
        for step in workflow['steps']
    ]}


def step_count(value: object) -> int:
    return len(normalize_workflow(value).get('steps', [None]))
