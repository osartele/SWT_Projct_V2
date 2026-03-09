import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentic_society import (
    GeminiCliInvoker,
    _critic_prompt,
    _generator_prompt,
    critic_verdict_is_approval,
    deterministic_regression_guard,
    extract_code_block,
)


class SocietyTests(unittest.TestCase):
    def test_regression_guard_flags_removed_assertions(self):
        original = """
        @Test
        public void addsValues() {
            assertEquals(2, calculator.add(1, 1));
        }
        """
        candidate = """
        @Test
        public void addsValues() {
            calculator.add(1, 1);
        }
        """
        flags = deterministic_regression_guard(original, candidate, 'add', 'addsValues')
        self.assertIn('assertions_removed', flags)
        self.assertIn('empty_or_missing_assertions', flags)

    def test_extract_code_block_strips_leading_labels_before_java_source(self):
        response = """
        evolved_repo/vitaminsaber/src/test/java/com/example/ExampleTest.java

        ```java
        package com.example;

        public class ExampleTest {
        }
        ```
        """
        extracted = extract_code_block(response)
        self.assertEqual('package com.example;\n\npublic class ExampleTest {\n}', extracted)

    def test_generator_prompt_uses_compact_context_without_paths(self):
        prompt = _generator_prompt(self._make_blackboard(), 'iterative_healing')
        self.assertIn('COMPACT CONTEXT:', prompt)
        self.assertIn('Your first non-whitespace token must be package, import, or public class.', prompt)
        self.assertIn('ORIGINAL TEST CODE:', prompt)
        self.assertNotIn('BLACKBOARD:', prompt)
        self.assertNotIn(r'C:\repo\sample', prompt)
        self.assertNotIn('C:/repo/sample', prompt)

    def test_critic_prompt_uses_compact_context_without_paths(self):
        prompt = _critic_prompt(self._make_blackboard(), 'package com.example;\npublic class ExampleTest {}')
        self.assertIn('COMPACT CONTEXT:', prompt)
        self.assertIn('stale_failure_summary', prompt)
        self.assertIn('org.junit.ComparisonFailure', prompt)
        self.assertNotIn('BLACKBOARD:', prompt)
        self.assertNotIn(r'C:\repo\sample', prompt)
        self.assertNotIn(r'C:\workspace\evolved_repo\ExampleTest.java', prompt)

    def test_critic_verdict_accept_alias_counts_as_approval(self):
        self.assertTrue(critic_verdict_is_approval('accept'))
        self.assertTrue(critic_verdict_is_approval('approved'))
        self.assertFalse(critic_verdict_is_approval('reject'))
        self.assertFalse(critic_verdict_is_approval(None))

    @mock.patch('agentic_society._is_windows', return_value=True)
    @mock.patch('agentic_society.shutil.which', return_value=r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe')
    @mock.patch('agentic_society.subprocess.run')
    def test_invoker_uses_powershell_env_bridge_on_windows(self, run_mock, _, __):
        run_mock.return_value = mock.Mock(returncode=0, stdout='candidate', stderr='')
        invoker = GeminiCliInvoker()

        with tempfile.TemporaryDirectory() as temp_dir:
            response, elapsed = invoker.invoke('generator', 'prompt text', Path(temp_dir), 'gemini')

        self.assertEqual('candidate', response)
        self.assertGreaterEqual(elapsed, 0.0)
        self.assertEqual(r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe', run_mock.call_args.args[0][0])
        self.assertEqual('gemini', json.loads(run_mock.call_args.kwargs['env']['AGONE_AGENT_COMMAND_JSON'])[0])
        self.assertEqual('prompt text', run_mock.call_args.kwargs['env']['AGONE_AGENT_PROMPT'])

    def _make_blackboard(self):
        return {
            'strategy': 'iterative_healing',
            'sample': {
                'sample_id': 'sample_1',
                'repo_path': r'C:\repo\sample',
                'test_class_name': 'ExampleTest',
                'test_method_name': 'updatesAssertion',
                'labeled_focal_method': 'emitHumanDescription',
                'labeled_focal_signature': 'void emitHumanDescription(StringBuilder builder, List<FieldBinding> bindings)',
                'focal_method_body': 'static void emitHumanDescription(...) { }',
            },
            'mapping': {
                'ast_prediction': 'emitHumanDescription',
            },
            'evolution': {
                'operator': 'predicate_inversion',
                'method_signature': 'void emitHumanDescription(StringBuilder builder, List<FieldBinding> bindings)',
                'evolved_body': 'static void emitHumanDescription(...) { if (i != count - 1) { builder.append("and "); } }',
                'diff': '@@\n-if (i == count - 1)\n+if (i != count - 1)',
            },
            'original_human_test': 'package com.example;\n\npublic class ExampleTest {\n    @Test public void updatesAssertion() {}\n}',
            'stale_human_result': {
                'summary': 'build_success',
                'stdout': "org.junit.ComparisonFailure: expected:<field 'one', field 'two', and field 'three'> but was:<and field 'one', and field 'two', field 'three'>\n    at C:\\workspace\\evolved_repo\\ExampleTest.java:32",
                'stderr': '',
            },
        }


if __name__ == '__main__':
    unittest.main()
