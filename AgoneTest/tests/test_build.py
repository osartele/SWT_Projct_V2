import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentic_build import (
    JavaToolchainSelection,
    _apply_toolchain_to_command,
    _build_java_env,
    _remove_readonly,
    _resolve_java_toolchain,
    create_sample_workspace,
    run_human_stale_check,
)
from agentic_types import BenchmarkSample, BuildExecutionResult, BuildMetadata, EvaluationLabel


class BuildTests(unittest.TestCase):
    def _make_jdk(self, java_home: Path, java_version: str) -> None:
        (java_home / 'bin').mkdir(parents=True)
        (java_home / 'lib').mkdir()
        (java_home / 'bin' / 'java.exe').write_text('', encoding='utf-8')
        (java_home / 'bin' / 'javac.exe').write_text('', encoding='utf-8')
        (java_home / 'lib' / 'tools.jar').write_text('', encoding='utf-8')
        (java_home / 'release').write_text('JAVA_VERSION="%s"\n' % java_version, encoding='utf-8')

    def _sample(self, root: Path, repo_path: Path | None = None, build_metadata: BuildMetadata | None = None) -> BenchmarkSample:
        return BenchmarkSample(
            sample_id='sample_0',
            dataset_path=root / 'sample.json',
            project_id='123',
            repo_path=repo_path,
            test_class_name='ExampleTest',
            test_class_path='src/test/java/ExampleTest.java',
            test_method_name='testExample',
            build_metadata=build_metadata,
            runnable=True,
            skip_reason=None,
            repository_url=None,
        )

    def _label(self) -> EvaluationLabel:
        return EvaluationLabel(
            sample_id='sample_0',
            project_id='123',
            focal_class_name='Example',
            focal_class_path='src/main/java/Example.java',
            labeled_focal_method='run',
            labeled_focal_signature='void run()',
            focal_method_body='void run() {}',
            raw_sample={},
        )

    def test_remove_readonly_retries_permission_error(self):
        remover = mock.Mock()

        with mock.patch('agentic_build.os.chmod') as chmod_mock:
            _remove_readonly(remover, 'readonly-file', (PermissionError, PermissionError(13, 'denied'), None))

        chmod_mock.assert_called_once()
        remover.assert_called_once_with('readonly-file')

    def test_build_java_env_discovers_matching_jdk_when_env_placeholder_is_invalid(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            jdk_home = root / '.jdks' / 'corretto-1.8.0_482'
            self._make_jdk(jdk_home, '1.8.0_482')

            with mock.patch.dict('agentic_build.os.environ', {'JAVA_HOME_8': '/Java/jdk1_8', 'PATH': 'C:\\Windows\\System32'}, clear=True):
                with mock.patch('agentic_build.Path.home', return_value=root):
                    env, error = _build_java_env('1.8', 'Windows')

        self.assertIsNone(error)
        self.assertEqual(str(jdk_home), env['JAVA_HOME'])
        self.assertTrue(env['PATH'].startswith(str(jdk_home / 'bin') + ';'))

    def test_build_java_env_returns_helpful_error_when_no_matching_jdk_exists(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with mock.patch.dict('agentic_build.os.environ', {'PATH': 'C:\\Windows\\System32'}, clear=True):
                with mock.patch('agentic_build.Path.home', return_value=root):
                    env, error = _build_java_env('1.8', 'Windows')

        self.assertIsNone(env)
        self.assertIn('JAVA_HOME_8', error)
        self.assertIn('tools.jar', error)

    def test_resolve_java_toolchain_uses_safe_launcher_and_closest_target_for_legacy_maven(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_root = root / 'repo'
            module_root = repo_root / 'module'
            module_root.mkdir(parents=True)
            wrapper_dir = repo_root / '.mvn' / 'wrapper'
            wrapper_dir.mkdir(parents=True)
            (wrapper_dir / 'maven-wrapper.properties').write_text(
                'distributionUrl=https://repo.maven.apache.org/maven2/org/apache/maven/apache-maven/3.9.9/apache-maven-3.9.9-bin.zip\n',
                encoding='utf-8',
            )

            jdk7 = root / '.jdks' / 'zulu-7'
            jdk8 = root / '.jdks' / 'corretto-1.8.0_482'
            self._make_jdk(jdk7, '1.7.0_352')
            self._make_jdk(jdk8, '1.8.0_482')

            build_metadata = BuildMetadata(
                build_system='maven',
                module_path=str(module_root),
                java_version='1.6',
                junit_version='4.10',
                testng_version=None,
                compiler_version='3.8.1',
                has_mockito=False,
            )

            with mock.patch.dict(
                'agentic_build.os.environ',
                {
                    'JAVA_HOME_6': str(jdk8),
                    'JAVA_HOME_7': str(jdk7),
                    'JAVA_HOME_8': str(jdk8),
                    'PATH': 'C:\\Windows\\System32',
                },
                clear=True,
            ):
                with mock.patch('agentic_build.Path.home', return_value=root):
                    toolchain, error = _resolve_java_toolchain(build_metadata, str(module_root), 'Windows')

        self.assertIsNone(error)
        self.assertEqual(str(jdk8), str(toolchain.launcher_home))
        self.assertEqual(str(jdk7), str(toolchain.target_home))
        self.assertEqual(8, toolchain.launcher_major)
        self.assertEqual(7, toolchain.target_major)

    def test_apply_toolchain_to_command_adds_maven_target_javac(self):
        toolchain = JavaToolchainSelection(
            launcher_home=Path('C:/Java/jdk8'),
            target_home=Path('C:/Java/jdk7'),
            launcher_major=8,
            target_major=7,
        )

        command = _apply_toolchain_to_command(['mvnw.cmd', 'clean', 'test'], 'maven', toolchain, 'Windows')

        self.assertEqual('mvnw.cmd', command[0])
        self.assertEqual('-Dmaven.compiler.fork=true', command[1])
        self.assertEqual(
            '-Dmaven.compiler.executable=%s' % (Path('C:/Java/jdk7') / 'bin' / 'javac.exe'),
            command[2],
        )
        self.assertEqual(['clean', 'test'], command[3:])

    def test_run_human_stale_check_uses_prepared_evolved_repo_without_reapplying_evolution(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sample_root = root / 'sample'
            evolved_root = sample_root / 'evolved_repo'
            evolved_root.mkdir(parents=True)
            sample = self._sample(root, root / 'repo')
            label = self._label()
            expected = BuildExecutionResult(True, 'stdout', 'stderr', 'build_success', 1, None, None, None, None)

            with mock.patch('agentic_build.instrument_workspace', return_value=('original', None)) as instrument_mock:
                with mock.patch('agentic_build.run_build_with_metrics', return_value=expected) as run_mock:
                    with mock.patch('agentic_build.restore_instrumentation') as restore_mock:
                        result = run_human_stale_check(sample, label, sample_root)

            instrument_mock.assert_called_once_with(sample, label, evolved_root)
            run_mock.assert_called_once_with(sample, label, str(evolved_root), evolved_root)
            restore_mock.assert_called_once_with(sample, None, 'original')
            self.assertEqual(expected, result)

    def test_create_sample_workspace_uses_readonly_handler_when_recreating(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_root = root / 'repo'
            workspace_root = root / 'workspaces'
            repo_root.mkdir()
            (repo_root / 'README.md').write_text('sample', encoding='utf-8')
            sample = self._sample(root, repo_root)
            existing_root = workspace_root / sample.project_id / sample.sample_id / 'iterative_healing'
            existing_root.mkdir(parents=True)

            with mock.patch('agentic_build.shutil.rmtree') as rmtree_mock:
                with mock.patch('agentic_build.shutil.copytree') as copytree_mock:
                    create_sample_workspace(sample, workspace_root, 'iterative_healing')

            self.assertEqual(_remove_readonly, rmtree_mock.call_args.kwargs['onerror'])
            self.assertEqual(2, copytree_mock.call_count)


if __name__ == '__main__':
    unittest.main()
