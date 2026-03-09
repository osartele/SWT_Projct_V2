import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentic_build import _remove_readonly, create_sample_workspace
from agentic_types import BenchmarkSample


class BuildTests(unittest.TestCase):
    def test_remove_readonly_retries_permission_error(self):
        remover = mock.Mock()

        with mock.patch('agentic_build.os.chmod') as chmod_mock:
            _remove_readonly(remover, 'readonly-file', (PermissionError, PermissionError(13, 'denied'), None))

        chmod_mock.assert_called_once()
        remover.assert_called_once_with('readonly-file')

    def test_create_sample_workspace_uses_readonly_handler_when_recreating(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_root = root / 'repo'
            workspace_root = root / 'workspaces'
            repo_root.mkdir()
            (repo_root / 'README.md').write_text('sample', encoding='utf-8')
            sample = BenchmarkSample(
                sample_id='sample_0',
                dataset_path=root / 'sample.json',
                project_id='123',
                repo_path=repo_root,
                focal_class_name='Example',
                focal_class_path='src/main/java/Example.java',
                test_class_name='ExampleTest',
                test_class_path='src/test/java/ExampleTest.java',
                test_method_name='testExample',
                labeled_focal_method='run',
                labeled_focal_signature='void run()',
                build_metadata=None,
                runnable=True,
                skip_reason=None,
                repository_url=None,
                focal_method_body='void run() {}',
                raw_sample={},
            )
            existing_root = workspace_root / sample.project_id / sample.sample_id / 'iterative_healing'
            existing_root.mkdir(parents=True)

            with mock.patch('agentic_build.shutil.rmtree') as rmtree_mock:
                with mock.patch('agentic_build.shutil.copytree') as copytree_mock:
                    create_sample_workspace(sample, workspace_root, 'iterative_healing')

            self.assertEqual(_remove_readonly, rmtree_mock.call_args.kwargs['onerror'])
            self.assertEqual(2, copytree_mock.call_count)


if __name__ == '__main__':
    unittest.main()
