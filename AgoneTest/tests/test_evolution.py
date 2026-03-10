import unittest
from pathlib import Path

from agentic_evolution import create_evolution
from agentic_types import BenchmarkSample, EvaluationLabel


class EvolutionTests(unittest.TestCase):
    def test_return_value_change_updates_method_body(self):
        sample = BenchmarkSample(
            sample_id='sample',
            dataset_path=Path('sample.json'),
            project_id='1',
            repo_path=Path('repo'),
            test_class_name='FlagTest',
            test_class_path='src/test/java/FlagTest.java',
            test_method_name='returnsTrue',
            build_metadata=None,
            runnable=True,
            skip_reason=None,
            repository_url=None,
        )
        label = EvaluationLabel(
            sample_id='sample',
            project_id='1',
            focal_class_name='Flag',
            focal_class_path='src/main/java/Flag.java',
            labeled_focal_method='isEnabled',
            labeled_focal_signature='boolean isEnabled()',
            focal_method_body='boolean isEnabled() { return true; }',
            raw_sample={},
        )
        evolution = create_evolution(sample, label, ['return_value_change'])
        self.assertEqual('return_value_change', evolution.operator)
        self.assertEqual('Flag', evolution.target_class_name)
        self.assertIn('return false;', evolution.evolved_body)


if __name__ == '__main__':
    unittest.main()
