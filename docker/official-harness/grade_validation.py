"""Keep official harness execution errors distinct from functional failures."""
import logging
import json
import shlex
from types import MethodType


def run_test_commands(env, commands, result_file, evidence=None):
    """Keep shell activation and surface test-runner diagnostics, not JSON noise."""
    if not commands:
        raise RuntimeError('AgentBench has no test command; no functional verdict.')
    # Setup lines fail fast; a test runner's nonzero exit can be a legitimate
    # functional failure, provided it produced a well-formed, nonempty report.
    script = '\n'.join(['set -e', 'rm -f -- ' + shlex.quote(result_file),
                        *commands[:-1], 'set +e', commands[-1]])
    execution = env.execute(script, timeout=False)
    raw = env.read_file(result_file)
    if evidence is not None:
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text(json.dumps({'commands': commands, 'execution': execution, 'rawResults': raw}, indent=2), encoding='utf-8')
    try:
        results = json.loads(raw)
        if not isinstance(results, dict) or not results or any(not isinstance(key, str) or not key or type(value) is not bool for key, value in results.items()):
            raise ValueError('Expected a nonempty test-name/boolean map')
    except (ValueError, TypeError) as error:
        raise RuntimeError(f'AgentBench test runner produced no valid {result_file}; '
                           f'exit={execution.get("returncode")}; no functional verdict. '
                           f'Runner output: {execution.get("output", "")[-4000:]}') from error
    return results


def configure_test_execution(instance, output=None):
    def repo_test(self, env):
        return run_test_commands(env, self.repo_test_commands, 'test_results.json', output / 'repo-tests.json' if output else None)
    def instance_test(self, env):
        return run_test_commands(env, self.test_commands, 'pr_test_results.json', output / 'instance-tests.json' if output else None)
    instance._run_repo_test = MethodType(repo_test, instance)
    instance._run_instance_test = MethodType(instance_test, instance)


def require_agentbench_result(evaluate):
    # The pinned upstream solve() catches exceptions and returns False for them.
    # Capture its dedicated error record, not arbitrary candidate test output.
    errors = []

    class Capture(logging.Handler):
        def emit(self, record):
            message = record.getMessage()
            if message.startswith('Error during solving instance '):
                errors.append(message)

    logger = logging.getLogger('agentbench.agentbench')
    handler = Capture(level=logging.ERROR)
    logger.addHandler(handler)
    try:
        result = evaluate()
    finally:
        logger.removeHandler(handler)
    if errors:
        raise RuntimeError('AgentBench evaluation failed; no functional verdict: ' + errors[0][:2000])
    if type(result) is not bool:
        raise ValueError('AgentBench did not return a boolean result.')
    return result
