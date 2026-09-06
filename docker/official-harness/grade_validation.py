"""Keep official harness execution errors distinct from functional failures."""
import logging


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
