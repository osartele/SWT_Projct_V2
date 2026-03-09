import unittest
from pathlib import Path

from agentic_mapping import map_sample
from agentic_types import BenchmarkSample


class MappingTests(unittest.TestCase):
    def test_ast_mapping_prefers_direct_invocation(self):
        sample = BenchmarkSample(
            sample_id='sample',
            dataset_path=Path('sample.json'),
            project_id='1',
            repo_path=Path('repo'),
            focal_class_name='Calculator',
            focal_class_path='src/main/java/Calculator.java',
            test_class_name='CalculatorTest',
            test_class_path='src/test/java/CalculatorTest.java',
            test_method_name='addsValues',
            labeled_focal_method='add',
            labeled_focal_signature='int add(int a, int b)',
            build_metadata=None,
            runnable=True,
            skip_reason=None,
            repository_url=None,
            focal_method_body='int add(int a, int b) { return a + b; }',
            raw_sample={
                'test_case': {'body': 'assertEquals(2, calculator.add(1, 1));', 'invocations': ['add', 'assertEquals']},
                'focal_class': {'methods': [{'identifier': 'add', 'constructor': False}, {'identifier': 'subtract', 'constructor': False}]},
            },
        )
        result = map_sample(sample)
        self.assertEqual('add', result.ast_prediction)
        self.assertTrue(result.ast_correct)


if __name__ == '__main__':
    unittest.main()
