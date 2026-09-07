import unittest
from worker.ctxbench_worker.workflows import normalize_workflow, workflow_request, step_count


class WorkflowTests(unittest.TestCase):
    def test_default_is_backward_compatible(self):
        for value in (None, {}, {'setupCommands': [], 'steps': [{'name': '', 'prompt': None}]}):
            self.assertEqual(normalize_workflow(value), {})
            self.assertIsNone(workflow_request(value, 'original prompt'))
            self.assertEqual(step_count(value), 1)

    def test_resolves_only_explicit_default_prompt_references(self):
        workflow = {'setupCommands': ['export EXAMPLE=1'], 'steps': [
            {'name': 'plan', 'prompt': 'Plan: {{default_prompt}}'}, {'name': 'code', 'prompt': 'Implement the plan'},
        ]}
        request = workflow_request(workflow, 'TASK TEXT')
        self.assertEqual([step['prompt'] for step in request['steps']], ['Plan: TASK TEXT', 'Implement the plan'])
        self.assertEqual(request['setupCommands'], ['export EXAMPLE=1'])
        self.assertEqual(workflow['steps'][0]['prompt'], 'Plan: {{default_prompt}}')
        self.assertNotIn('AGENTS.md', str(request))

    def test_rejects_invalid_shapes_without_echoing_prompts_or_commands(self):
        for value in ([1], {'unknown': 'PRIVATE'}, {'steps': []}, {'steps': 'PRIVATE'}, {'steps': [{'prompt': ''}]},
                      {'steps': [{'prompt': 'PRIVATE\0'}]}, {'setupCommands': ['']}, {'setupCommands': [123]},
                      {'setupCommands': ['PRIVATE\0']}, {'steps': [{'prompt': 'PRIVATE', 'extra': True}]},
                      {'steps': [{'prompt': 'PRIVATE'}] * 51}, {'setupCommands': ['PRIVATE'] * 21}):
            with self.subTest(kind=type(value).__name__):
                with self.assertRaises(ValueError) as error:
                    normalize_workflow(value)
                self.assertNotIn('PRIVATE', str(error.exception))


if __name__ == '__main__':
    unittest.main()
