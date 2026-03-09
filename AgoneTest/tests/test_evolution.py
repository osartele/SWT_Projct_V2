import unittest
from pathlib import Path

from agentic_evolution import create_evolution
from agentic_types import BenchmarkSample


class EvolutionTests(unittest.TestCase):
    def test_return_value_change_updates_method_body(self):
        sample = BenchmarkSample(
            sample_id='sample',
            dataset_path=Path('sample.json'),
            project_id='1',
            repo_path=Path('repo'),
            focal_class_name='Flag',
            focal_class_path='src/main/java/Flag.java',
            test_class_name='FlagTest',
            test_class_path='src/test/java/FlagTest.java',
            test_method_name='returnsTrue',
            labeled_focal_method='isEnabled',
            labeled_focal_signature='boolean isEnabled()',
            build_metadata=None,
            runnable=True,
            skip_reason=None,
            repository_url=None,
            focal_method_body='boolean isEnabled() { return true; }',
            raw_sample={},
        )
        evolution = create_evolution(sample, ['return_value_change'])
        self.assertEqual('return_value_change', evolution.operator)
        self.assertIn('return false;', evolution.evolved_body)


if __name__ == '__main__':
    unittest.main()
