import shutil
import tempfile
import unittest
from pathlib import Path

from agentic_mapping import map_sample
from agentic_types import BenchmarkSample, BuildMetadata, EvaluationLabel


class MappingTests(unittest.TestCase):
    def _java_available(self) -> bool:
        return bool(shutil.which('javac') or shutil.which('javac.exe')) and bool(shutil.which('java') or shutil.which('java.exe'))

    def _config(self, root: Path):
        return {
            'paths': {
                'dataset_dir': str(root / 'dataset'),
                'repos_dir': str(root / 'repos'),
                'output_dir': str(root / 'output'),
                'workspace_dir': str(root / 'workspaces'),
                'mapper_cli': str(Path(__file__).resolve().parents[1] / 'mapper_cli'),
            },
            'filters': {'project_ids': [], 'sample_ids': [], 'max_samples': None},
            'mapping': {'backend': 'java_sidecar', 'scope': 'module_then_repo', 'top_k': 5},
        }

    def _sample(self, root: Path, repo_root: Path) -> BenchmarkSample:
        return BenchmarkSample(
            sample_id='sample_0',
            dataset_path=root / 'dataset' / 'sample_0.json',
            project_id='1',
            repo_path=repo_root,
            test_class_name='CalculatorTest',
            test_class_path='src/test/java/example/CalculatorTest.java',
            test_method_name='addsValues',
            build_metadata=BuildMetadata(
                build_system='maven',
                module_path=str(repo_root),
                java_version='1.8',
                junit_version='4.12',
                testng_version=None,
                compiler_version='3.9.9',
                has_mockito=False,
            ),
            runnable=True,
            skip_reason=None,
            repository_url='https://example.com/repo.git',
        )

    def _label(self) -> EvaluationLabel:
        return EvaluationLabel(
            sample_id='sample_0',
            project_id='1',
            focal_class_name='Calculator',
            focal_class_path='src/main/java/example/Calculator.java',
            labeled_focal_method='add',
            labeled_focal_signature='int add(int left, int right)',
            focal_method_body='int add(int left, int right) { return left + right; }',
            raw_sample={},
        )

    def _write_project(self, repo_root: Path, test_body: str) -> None:
        main_dir = repo_root / 'src' / 'main' / 'java' / 'example'
        test_dir = repo_root / 'src' / 'test' / 'java' / 'example'
        main_dir.mkdir(parents=True)
        test_dir.mkdir(parents=True)
        (repo_root / 'pom.xml').write_text('<project xmlns="http://maven.apache.org/POM/4.0.0"></project>', encoding='utf-8')
        (main_dir / 'Calculator.java').write_text(
            'package example;\n\n'
            'public class Calculator {\n'
            '    public int add(int left, int right) { return left + right; }\n'
            '    public int subtract(int left, int right) { return left - right; }\n'
            '}\n',
            encoding='utf-8',
        )
        (test_dir / 'CalculatorTest.java').write_text(test_body, encoding='utf-8')

    def test_ast_mapping_prefers_direct_instance_invocation(self):
        if not self._java_available():
            self.skipTest('java toolchain unavailable')
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_root = root / 'repo'
            test_body = (
                'package example;\n\n'
                'import org.junit.Test;\n'
                'import static org.junit.Assert.assertEquals;\n\n'
                'public class CalculatorTest {\n'
                '    @Test\n'
                '    public void addsValues() {\n'
                '        Calculator calculator = new Calculator();\n'
                '        assertEquals(2, calculator.add(1, 1));\n'
                '    }\n'
                '}\n'
            )
            self._write_project(repo_root, test_body)
            result = map_sample(self._sample(root, repo_root), self._label(), self._config(root))
        self.assertEqual('add', result.ast_prediction)
        self.assertTrue(result.ast_correct)
        self.assertEqual('src/main/java/example/Calculator.java', result.ast_prediction_class_path)

    def test_ast_mapping_expands_same_class_helper_methods(self):
        if not self._java_available():
            self.skipTest('java toolchain unavailable')
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_root = root / 'repo'
            test_body = (
                'package example;\n\n'
                'import org.junit.Test;\n'
                'import static org.junit.Assert.assertEquals;\n\n'
                'public class CalculatorTest {\n'
                '    @Test\n'
                '    public void addsValues() {\n'
                '        verifySum(1, 1, 2);\n'
                '    }\n\n'
                '    private void verifySum(int left, int right, int expected) {\n'
                '        Calculator calculator = new Calculator();\n'
                '        assertEquals(expected, calculator.add(left, right));\n'
                '    }\n'
                '}\n'
            )
            self._write_project(repo_root, test_body)
            result = map_sample(self._sample(root, repo_root), self._label(), self._config(root))
        self.assertEqual('add', result.ast_prediction)
        self.assertTrue(result.ast_correct)
        self.assertIn('verifySum', result.ast_evidence.get('backend', {}).get('helper_expansion', []))


if __name__ == '__main__':
    unittest.main()
