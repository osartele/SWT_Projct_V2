from __future__ import annotations

import os
import platform
import re
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd

import errorCorrection
import gradleLib
import mavenLib
import utils
from agentic_types import BenchmarkSample, BuildExecutionResult, EvolutionSpec


def _remove_readonly(func, path: str, exc_info) -> None:
    _, error, _ = exc_info
    if not isinstance(error, PermissionError):
        raise error
    os.chmod(path, stat.S_IWRITE)
    func(path)


def create_sample_workspace(sample: BenchmarkSample, workspace_root: Path, strategy: str) -> Path:
    sample_root = workspace_root / sample.project_id / sample.sample_id / strategy
    baseline_root = sample_root / 'baseline_repo'
    evolved_root = sample_root / 'evolved_repo'
    if sample_root.exists():
        shutil.rmtree(sample_root, onerror=_remove_readonly)
    baseline_root.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(str(sample.repo_path), str(baseline_root))
    shutil.copytree(str(sample.repo_path), str(evolved_root))
    return sample_root


def _build_dataframe(sample: BenchmarkSample) -> pd.DataFrame:
    return pd.DataFrame([
        {
            'Project': int(sample.project_id) if sample.project_id.isdigit() else sample.project_id,
            'Focal_Class': sample.focal_class_name,
            'Test_Class': sample.test_class_name,
            'Focal_Path': sample.focal_class_path,
            'Test_Path': sample.test_class_path,
            'Module': None,
        }
    ])


def _method_signature_pattern(signature: str, identifier: str) -> Optional[re.Pattern]:
    if not signature:
        return None
    parameters_match = re.search(r'\((.*)\)', signature)
    parameters = parameters_match.group(1) if parameters_match else ''
    parameter_count = 0 if not parameters.strip() else len([part for part in parameters.split(',') if part.strip()])
    param_pattern = r'\([^)]*\)'
    if parameter_count == 0:
        param_pattern = r'\(\s*\)'
    escaped_identifier = re.escape(identifier)
    return re.compile(r'([^{;]*\b%s\s*%s\s*\{)' % (escaped_identifier, param_pattern), re.MULTILINE)


def apply_evolution_spec(evolution: EvolutionSpec, repo_root: Path) -> bool:
    target_path = repo_root / Path(evolution.target_file)
    if not target_path.exists():
        return False
    content = target_path.read_text(encoding='utf-8')
    if evolution.original_body in content:
        updated = content.replace(evolution.original_body, evolution.evolved_body, 1)
        target_path.write_text(updated, encoding='utf-8')
        return True

    pattern = _method_signature_pattern(evolution.method_signature, evolution.method_identifier)
    if pattern is None:
        return False
    match = pattern.search(content)
    if match is None:
        return False
    start = match.start(1)
    body_start = content.find('{', match.end(1) - 1)
    depth = 0
    end = None
    for index in range(body_start, len(content)):
        char = content[index]
        if char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                end = index + 1
                break
    if end is None:
        return False
    updated = content[:start] + evolution.evolved_body + content[end:]
    target_path.write_text(updated, encoding='utf-8')
    return True


def instrument_workspace(sample: BenchmarkSample, repo_root: Path) -> Tuple[object, Optional[str]]:
    dataframe = _build_dataframe(sample)
    build_metadata = sample.build_metadata
    if build_metadata is None:
        return None, None
    module_path = Path(build_metadata.module_path)
    if sample.repo_path is not None:
        relative_module = module_path.relative_to(sample.repo_path)
        workspace_module = repo_root / relative_module
    else:
        workspace_module = repo_root
    if build_metadata.build_system == 'maven':
        original = mavenLib.edit_pom_file(str(workspace_module), dataframe, build_metadata.junit_version or '4', build_metadata.testng_version)
    else:
        original = gradleLib.edit_build_gradle_file(str(workspace_module), dataframe, build_metadata.junit_version or '4')
    return original, str(workspace_module)


def restore_instrumentation(sample: BenchmarkSample, workspace_module: Optional[str], original: object) -> None:
    if original is None or workspace_module is None:
        return
    build_metadata = sample.build_metadata
    if build_metadata is None:
        return
    if build_metadata.build_system == 'maven':
        original.write(os.path.join(workspace_module, 'pom.xml'))
    else:
        gradleLib.write_build_gradle(workspace_module, original)


def _test_selector(sample: BenchmarkSample) -> str:
    if 'test/java/' in sample.test_class_path:
        return sample.test_class_path.split('test/java/')[1].replace('/', '.').replace('.java', '')
    if 'src\\test\\java\\' in sample.test_class_path:
        return sample.test_class_path.split('src\\test\\java\\')[1].replace('\\', '.').replace('.java', '')
    return sample.test_class_name


def run_build_with_metrics(sample: BenchmarkSample, module_path: str, repo_root: Optional[Path] = None) -> BuildExecutionResult:
    build_metadata = sample.build_metadata
    if build_metadata is None:
        return BuildExecutionResult(False, '', '', 'missing_build_metadata', 0, None, None, None, None)

    selector = _test_selector(sample)
    system = platform.system()
    if build_metadata.build_system == 'maven':
        command = mavenLib.resolve_maven_command(system, module_path) + ['-Dtest=%s' % selector, '-Drat.skip=true', '-DfailIfNoTests=false', '-Dcheckstyle.skip=true', 'clean', 'verify', 'jacoco:prepare-agent', 'jacoco:report', 'org.pitest:pitest-maven:mutationCoverage']
    else:
        executable = 'gradle.bat' if system == 'Windows' else 'gradle'
        command = [executable, 'clean', 'test', '--tests=%s' % selector, 'pitest']

    try:
        result = subprocess.run(command, cwd=module_path, capture_output=True, text=True, timeout=900)
    except Exception as exc:
        return BuildExecutionResult(False, '', str(exc), str(exc), 0, None, None, None, None)

    if build_metadata.build_system == 'maven':
        success = 'BUILD SUCCESS' in result.stdout
        summary = 'build_success' if success else errorCorrection.extract_errors(result.stdout, result.stderr)
    else:
        success = 'BUILD SUCCESSFUL' in result.stdout
        summary = 'build_success' if success else errorCorrection.extract_gradle_errors(result.stdout, result.stderr)

    branch = None
    line = None
    method = None
    mutation = None
    if success:
        measures = utils.retrieve_code_coverage_and_cyclomatic_complexity(
            str(repo_root or module_path),
            _build_dataframe(sample),
            sample.project_id,
            'Maven' if build_metadata.build_system == 'maven' else 'Gradle',
            None,
        )
        if measures is not None and not measures.empty:
            row = measures.iloc[0]
            branch = _maybe_float(row.get('Branch_coverage'))
            line = _maybe_float(row.get('Line_coverage'))
            method = _maybe_float(row.get('Method_coverage'))
            mutation = _maybe_float(row.get('Mutation_Coverage'))

    return BuildExecutionResult(success=success, stdout=result.stdout, stderr=result.stderr, summary=summary, compilation=1 if success else 0, branch_coverage=branch, line_coverage=line, method_coverage=method, mutation_coverage=mutation)


def write_candidate_code(repo_root: Path, sample: BenchmarkSample, code: str) -> Path:
    target = repo_root / Path(sample.test_class_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(code, encoding='utf-8')
    return target


def file_sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _maybe_float(value: object) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def run_human_baseline(sample: BenchmarkSample, sample_root: Path) -> BuildExecutionResult:
    repo_root = sample_root / 'baseline_repo'
    original, module_path = instrument_workspace(sample, repo_root)
    try:
        return run_build_with_metrics(sample, module_path or str(repo_root), repo_root)
    finally:
        restore_instrumentation(sample, module_path, original)


def run_human_stale_check(sample: BenchmarkSample, sample_root: Path, evolution: EvolutionSpec) -> BuildExecutionResult:
    repo_root = sample_root / 'evolved_repo'
    apply_evolution_spec(evolution, repo_root)
    original, module_path = instrument_workspace(sample, repo_root)
    try:
        return run_build_with_metrics(sample, module_path or str(repo_root), repo_root)
    finally:
        restore_instrumentation(sample, module_path, original)

