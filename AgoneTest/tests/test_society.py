import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentic_society import (
    GeminiCliInvoker,
    _critic_prompt,
    _generator_prompt,
    _string_list,
    critic_verdict_is_approval,
    deterministic_regression_guard,
    extract_code_block,
    extract_method_source_from_file,
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

    def test_extract_method_source_is_anchored_to_method_signature(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / 'Example.java'
            source_path.write_text(
                'package com.example;\n\n'
                'public class Example {\n'
                '    static String helper() {\n'
                '        return "helper";\n'
                '    }\n\n'
                '    static void emitHumanDescription(StringBuilder builder, java.util.List<String> values) {\n'
                '        builder.append(values.size());\n'
                '    }\n'
                '}\n',
                encoding='utf-8',
            )
            extracted = extract_method_source_from_file(
                source_path,
                'void emitHumanDescription(StringBuilder builder, java.util.List<String> values)',
                'emitHumanDescription',
            )
        self.assertTrue(extracted.lstrip().startswith('static void emitHumanDescription'))
        self.assertNotIn('return "helper";', extracted)

    def test_string_list_normalizes_scalar_and_iterable_values(self):
        self.assertEqual([], _string_list(None))
        self.assertEqual(['single'], _string_list('single'))
        self.assertEqual(['one', 'two'], _string_list(['one', ' two ', '']))
        self.assertEqual(['123'], _string_list(123))

    def test_generator_prompt_uses_runtime_context_without_oracle_fields(self):
        prompt = _generator_prompt(self._make_blackboard(), 'iterative_healing')
        self.assertIn('COMPACT CONTEXT:', prompt)
        self.assertIn('CONTEXT POLICY: ast_predicted', prompt)
        self.assertIn('mapped_focal_method', prompt)
        self.assertIn('mapped_method_diff', prompt)
        self.assertNotIn('labeled_focal_method', prompt)
        self.assertNotIn('focal_method_body', prompt)
        self.assertNotIn(r'C:\repo\sample', prompt)

    def test_critic_prompt_uses_runtime_context_without_oracle_fields(self):
        prompt = _critic_prompt(self._make_blackboard(), 'package com.example;\npublic class ExampleTest {}')
        self.assertIn('COMPACT CONTEXT:', prompt)
        self.assertIn('stale_failure_summary', prompt)
        self.assertIn('mapped_focal_method', prompt)
        self.assertNotIn('labeled_focal_method', prompt)
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
            'context_policy': 'ast_predicted',
            'sample': {
                'sample_id': 'sample_1',
                'test_class_name': 'ExampleTest',
                'test_method_name': 'updatesAssertion',
            },
            'mapping_summary': {
                'ast_prediction': 'emitHumanDescription',
                'ast_prediction_signature': 'void emitHumanDescription(StringBuilder builder, List<FieldBinding> bindings)',
                'ast_prediction_class_path': 'src/main/java/com/example/Example.java',
                'ast_confidence': 0.9,
            },
            'runtime_context': {
                'sample_id': 'sample_1',
                'context_policy': 'ast_predicted',
                'test_class_name': 'ExampleTest',
                'test_method_name': 'updatesAssertion',
                'mapped_focal_method': 'emitHumanDescription',
                'mapped_focal_signature': 'void emitHumanDescription(StringBuilder builder, List<FieldBinding> bindings)',
                'mapped_focal_class_path': 'src/main/java/com/example/Example.java',
                'mapping_confidence': 0.9,
                'mapped_evolved_method_body': 'static void emitHumanDescription(...) { }',
                'mapped_method_diff': '@@\n-if (i == count - 1)\n+if (i != count - 1)',
                'stale_failure_summary': "org.junit.ComparisonFailure: expected:<field 'one'> but was:<and field 'one'>",
            },
            'original_human_test': 'package com.example;\n\npublic class ExampleTest {\n    @Test public void updatesAssertion() {}\n}',
        }


if __name__ == '__main__':
    unittest.main()

