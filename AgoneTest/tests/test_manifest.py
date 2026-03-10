import json
import tempfile
import unittest
from pathlib import Path

from agentic_manifest import build_manifest


class ManifestTests(unittest.TestCase):
    def test_manifest_marks_missing_repo_as_skipped_and_extracts_eval_label(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dataset_dir = root / 'dataset'
            repos_dir = root / 'repos'
            dataset_dir.mkdir()
            repos_dir.mkdir()
            sample = {
                'repository': {'repo_id': 123, 'url': 'https://example.com/repo.git'},
                'focal_class': {'identifier': 'Foo', 'file': 'src/main/java/Foo.java'},
                'test_class': {'identifier': 'FooTest', 'file': 'src/test/java/FooTest.java'},
                'test_case': {'identifier': 'testFoo', 'body': '', 'invocations': []},
                'focal_method': {'identifier': 'foo', 'signature': 'void foo()', 'body': 'void foo() {}'},
            }
            (dataset_dir / '123_0.json').write_text(json.dumps(sample), encoding='utf-8')
            config = {
                'paths': {
                    'dataset_dir': str(dataset_dir),
                    'repos_dir': str(repos_dir),
                    'output_dir': str(root / 'output'),
                    'workspace_dir': str(root / 'workspaces'),
                    'mapper_cli': str(root / 'mapper_cli'),
                },
                'filters': {'project_ids': [], 'sample_ids': [], 'max_samples': None},
            }
            manifest, labels = build_manifest(config)
            self.assertEqual(1, len(manifest))
            self.assertFalse(manifest[0].runnable)
            self.assertEqual('missing_repo', manifest[0].skip_reason)
            self.assertEqual(1, len(labels))
            self.assertEqual('foo', labels[0].labeled_focal_method)
            self.assertEqual('src/main/java/Foo.java', labels[0].focal_class_path)


if __name__ == '__main__':
    unittest.main()
