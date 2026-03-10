from __future__ import annotations

import os
import platform
import re
import shutil
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple

import pandas as pd

import errorCorrection
import gradleLib
import mavenLib
import utils
from agentic_types import BenchmarkSample, BuildExecutionResult, BuildMetadata, EvaluationLabel, EvolutionSpec


_KNOWN_JAVA_MAJORS = ('5', '6', '7', '8', '11', '17', '21')


@dataclass(frozen=True)
class JavaToolchainSelection:
    launcher_home: Path
    target_home: Path
    launcher_major: int
    target_major: int


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


def _normalize_java_major(java_version: Optional[str]) -> str:
    value = (java_version or '').strip()
    if value.startswith('1.'):
        parts = value.split('.', 2)
        return parts[1] if len(parts) > 1 else value
    match = re.search(r'\d+', value)
    return match.group(0) if match else ''


def _java_major_number(java_version: Optional[str]) -> Optional[int]:
    major = _normalize_java_major(java_version)
    return int(major) if major.isdigit() else None


def _expected_java_home_env(java_version: Optional[str]) -> str:
    major = _normalize_java_major(java_version)
    if major in _KNOWN_JAVA_MAJORS:
        return 'JAVA_HOME_%s' % major
    return 'JAVA_HOME_DEFAULT'


def _java_release_version(java_home: Path) -> Optional[str]:
    release_file = java_home / 'release'
    if not release_file.exists():
        return None
    try:
        for line in release_file.read_text(encoding='utf-8', errors='ignore').splitlines():
            if line.startswith('JAVA_VERSION='):
                return line.split('=', 1)[1].strip().strip('"')
    except OSError:
        return None
    return None


def _java_home_matches_version(java_home: Path, java_version: Optional[str]) -> bool:
    expected_major = _normalize_java_major(java_version)
    if not expected_major:
        return True
    release_version = _java_release_version(java_home)
    if release_version:
        return _normalize_java_major(release_version) == expected_major
    folder_name = java_home.name.lower()
    if expected_major in {'5', '6', '7', '8'}:
        tokens = ['1.%s' % expected_major, 'jdk%s' % expected_major, 'java%s' % expected_major]
    else:
        tokens = ['jdk-%s' % expected_major, 'jdk%s' % expected_major, 'java%s' % expected_major, '%s.' % expected_major]
    return any(token in folder_name for token in tokens)


def _is_valid_java_home(java_home: Path, system: str, java_version: Optional[str]) -> bool:
    java_name = 'java.exe' if system == 'Windows' else 'java'
    javac_name = 'javac.exe' if system == 'Windows' else 'javac'
    if not (java_home / 'bin' / java_name).is_file():
        return False
    if not (java_home / 'bin' / javac_name).is_file():
        return False
    major = _normalize_java_major(java_version)
    if major in {'5', '6', '7', '8'} and not (java_home / 'lib' / 'tools.jar').is_file():
        return False
    return True


def _java_search_roots(system: str) -> Tuple[Path, ...]:
    roots = [Path.home() / '.jdks']
    if system == 'Windows':
        roots.extend([
            Path('C:/Program Files/Java'),
            Path('C:/Program Files (x86)/Java'),
            Path('C:/Program Files/Eclipse Adoptium'),
            Path('C:/Program Files/Microsoft'),
            Path('C:/Program Files/Zulu'),
        ])
    else:
        roots.extend([Path('/usr/lib/jvm'), Path('/Library/Java/JavaVirtualMachines')])
    return tuple(root for root in roots if root.exists())


def _clean_java_home_value(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = value.strip().strip('"').strip("'")
    return cleaned or None


def _java_home_major(java_home: Path) -> Optional[int]:
    release_major = _java_major_number(_java_release_version(java_home))
    if release_major is not None:
        return release_major
    folder_name = java_home.name.lower()
    match = re.search(r'(?:^|[^0-9])(?:1\.)?(5|6|7|8|11|17|21)(?:[^0-9]|$)', folder_name)
    if match is None:
        return None
    return int(match.group(1))


def _iter_java_home_candidates(system: str) -> Iterable[Tuple[Optional[str], Path]]:
    seen = set()
    env_names = ('JAVA_HOME_LAUNCHER', 'JAVA_HOME_TARGET', 'JAVA_HOME') + tuple(
        'JAVA_HOME_%s' % major for major in _KNOWN_JAVA_MAJORS
    ) + ('JAVA_HOME_DEFAULT',)
    for env_name in env_names:
        value = _clean_java_home_value(os.getenv(env_name))
        if not value:
            continue
        java_home = Path(value)
        key = str(java_home).lower()
        if key in seen:
            continue
        seen.add(key)
        yield env_name, java_home

    javac_name = 'javac.exe' if system == 'Windows' else 'javac'
    for root in _java_search_roots(system):
        for javac_path in sorted(root.glob('**/bin/%s' % javac_name)):
            java_home = javac_path.parent.parent
            key = str(java_home).lower()
            if key in seen:
                continue
            seen.add(key)
            yield None, java_home


def _candidate_preference_rank(source_name: Optional[str], preferred_envs: Tuple[str, ...]) -> int:
    if source_name in preferred_envs:
        return preferred_envs.index(source_name)
    if source_name is not None:
        return len(preferred_envs)
    return len(preferred_envs) + 1


def _select_java_home(
    java_version: Optional[str],
    system: str,
    minimum_major: Optional[int],
    preferred_envs: Tuple[str, ...],
    override_env: Optional[str] = None,
) -> Optional[Path]:
    validation_version = java_version or (str(minimum_major) if minimum_major is not None else None)

    if override_env is not None:
        override_value = _clean_java_home_value(os.getenv(override_env))
        if override_value:
            override_home = Path(override_value)
            override_major = _java_home_major(override_home)
            if (
                override_major is not None
                and (minimum_major is None or override_major >= minimum_major)
                and _is_valid_java_home(override_home, system, validation_version)
            ):
                return override_home

    candidates = []
    for source_name, java_home in _iter_java_home_candidates(system):
        candidate_major = _java_home_major(java_home)
        if candidate_major is None:
            continue
        if minimum_major is not None and candidate_major < minimum_major:
            continue
        if not _is_valid_java_home(java_home, system, validation_version):
            continue
        distance = candidate_major - minimum_major if minimum_major is not None else 0
        candidates.append(
            (
                distance,
                _candidate_preference_rank(source_name, preferred_envs),
                candidate_major,
                str(java_home).lower(),
                java_home,
            )
        )
    if not candidates:
        return None
    return sorted(candidates)[0][-1]


def _build_java_env_for_home(java_home: Path, system: str) -> Dict[str, str]:
    env = os.environ.copy()
    java_bin = str(java_home / 'bin')
    separator = ';' if system == 'Windows' else ':'
    env['JAVA_HOME'] = str(java_home)
    env['PATH'] = '%s%s%s' % (java_bin, separator, env.get('PATH', '')) if env.get('PATH') else java_bin
    return env


def _discover_java_home(java_version: Optional[str], system: str) -> Optional[Path]:
    return _select_java_home(java_version, system, _java_major_number(java_version), tuple())


def _build_java_env(java_version: Optional[str], system: str):
    expected_env = _expected_java_home_env(java_version)
    java_home = _select_java_home(
        java_version,
        system,
        _java_major_number(java_version),
        (expected_env, 'JAVA_HOME_TARGET', 'JAVA_HOME', 'JAVA_HOME_DEFAULT'),
        override_env='JAVA_HOME_TARGET',
    )
    if java_home is None:
        message = 'missing_jdk_for_java_%s: configure `%s` in AgoneTest/.env to a JDK home with `javac`' % (java_version or 'unknown', expected_env)
        if _normalize_java_major(java_version) in {'5', '6', '7', '8'}:
            message += ' and `lib/tools.jar`'
        return None, message
    return _build_java_env_for_home(java_home, system), None


def _find_maven_wrapper_properties(module_path: str) -> Optional[Path]:
    current = Path(module_path).resolve()
    if current.is_file():
        current = current.parent
    for root in (current, *current.parents):
        candidate = root / '.mvn' / 'wrapper' / 'maven-wrapper.properties'
        if candidate.is_file():
            return candidate
    return None


def _extract_maven_wrapper_version(module_path: str) -> Optional[str]:
    properties_path = _find_maven_wrapper_properties(module_path)
    if properties_path is None:
        return None
    try:
        content = properties_path.read_text(encoding='utf-8', errors='ignore')
    except OSError:
        return None
    match = re.search(r'/apache-maven/([^/]+)/apache-maven-[^/]+\.zip', content)
    if match is None:
        return None
    return match.group(1)


def _parse_version_tuple(version: Optional[str]) -> Tuple[int, ...]:
    if not version:
        return tuple()
    parts = re.findall(r'\d+', version)
    return tuple(int(part) for part in parts[:3])


def _minimum_maven_launcher_major(maven_version: Optional[str]) -> int:
    parsed = _parse_version_tuple(maven_version)
    if not parsed:
        return 8
    if parsed >= (3, 9):
        return 8
    if parsed >= (3, 3):
        return 7
    return 5


def _minimum_launcher_java_major(build_system: str, module_path: str, target_major: int) -> int:
    if build_system == 'maven':
        return max(target_major, _minimum_maven_launcher_major(_extract_maven_wrapper_version(module_path)))
    if build_system == 'gradle':
        return max(target_major, 8)
    return target_major


def _resolve_java_toolchain(build_metadata: BuildMetadata, module_path: str, system: str):
    target_major = _java_major_number(build_metadata.java_version) or 8
    target_expected_env = _expected_java_home_env(build_metadata.java_version)
    target_home = _select_java_home(
        build_metadata.java_version,
        system,
        target_major,
        (target_expected_env, 'JAVA_HOME_TARGET', 'JAVA_HOME', 'JAVA_HOME_DEFAULT'),
        override_env='JAVA_HOME_TARGET',
    )
    if target_home is None:
        message = 'missing_target_jdk_for_java_%s: configure `%s` or `JAVA_HOME_TARGET` in AgoneTest/.env to a compatible JDK home with `javac`' % (
            build_metadata.java_version or 'unknown',
            target_expected_env,
        )
        if target_major <= 8:
            message += ' and `lib/tools.jar`'
        return None, message

    launcher_major = _minimum_launcher_java_major(build_metadata.build_system, module_path, target_major)
    launcher_expected_env = _expected_java_home_env(str(launcher_major))
    launcher_home = _select_java_home(
        str(launcher_major),
        system,
        launcher_major,
        ('JAVA_HOME_LAUNCHER', launcher_expected_env, 'JAVA_HOME', 'JAVA_HOME_DEFAULT'),
        override_env='JAVA_HOME_LAUNCHER',
    )
    if launcher_home is None:
        message = 'missing_launcher_jdk_for_java_%s: configure `JAVA_HOME_LAUNCHER` or `%s` in AgoneTest/.env to a compatible JDK home with `javac`' % (
            launcher_major,
            launcher_expected_env,
        )
        if launcher_major <= 8:
            message += ' and `lib/tools.jar`'
        return None, message

    return JavaToolchainSelection(
        launcher_home=launcher_home,
        target_home=target_home,
        launcher_major=_java_home_major(launcher_home) or launcher_major,
        target_major=_java_home_major(target_home) or target_major,
    ), None


def _java_binary(java_home: Path, executable: str, system: str) -> str:
    suffix = '.exe' if system == 'Windows' else ''
    return str(java_home / 'bin' / ('%s%s' % (executable, suffix)))


def _apply_toolchain_to_command(command, build_system: str, toolchain: JavaToolchainSelection, system: str):
    if build_system == 'maven' and toolchain.target_home != toolchain.launcher_home:
        return [
            command[0],
            '-Dmaven.compiler.fork=true',
            '-Dmaven.compiler.executable=%s' % _java_binary(toolchain.target_home, 'javac', system),
            *command[1:],
        ]
    if build_system == 'gradle' and toolchain.target_home != toolchain.launcher_home:
        return [
            command[0],
            '-Dorg.gradle.java.installations.paths=%s' % toolchain.target_home,
            '-Dorg.gradle.java.installations.auto-download=false',
            *command[1:],
        ]
    return command


def _build_dataframe(sample: BenchmarkSample, label: EvaluationLabel) -> pd.DataFrame:
    return pd.DataFrame([
        {
            'Project': int(sample.project_id) if sample.project_id.isdigit() else sample.project_id,
            'Focal_Class': label.focal_class_name,
            'Test_Class': sample.test_class_name,
            'Focal_Path': label.focal_class_path,
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


def instrument_workspace(sample: BenchmarkSample, label: EvaluationLabel, repo_root: Path) -> Tuple[object, Optional[str]]:
    dataframe = _build_dataframe(sample, label)
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


def run_build_with_metrics(sample: BenchmarkSample, label: EvaluationLabel, module_path: str, repo_root: Optional[Path] = None) -> BuildExecutionResult:
    build_metadata = sample.build_metadata
    if build_metadata is None:
        return BuildExecutionResult(False, '', '', 'missing_build_metadata', 0, None, None, None, None)

    selector = _test_selector(sample)
    system = platform.system()
    toolchain, java_error = _resolve_java_toolchain(build_metadata, module_path, system)
    if java_error is not None:
        return BuildExecutionResult(False, '', java_error, java_error, 0, None, None, None, None)
    env = _build_java_env_for_home(toolchain.launcher_home, system)
    if build_metadata.build_system == 'maven':
        command = mavenLib.resolve_maven_command(system, module_path) + ['-Dtest=%s' % selector, '-Drat.skip=true', '-DfailIfNoTests=false', '-Dcheckstyle.skip=true', 'clean', 'verify', 'jacoco:prepare-agent', 'jacoco:report', 'org.pitest:pitest-maven:mutationCoverage']
    else:
        executable = 'gradle.bat' if system == 'Windows' else 'gradle'
        command = [executable, 'clean', 'test', '--tests=%s' % selector, 'pitest']
    command = _apply_toolchain_to_command(command, build_metadata.build_system, toolchain, system)

    try:
        result = subprocess.run(command, cwd=module_path, capture_output=True, text=True, timeout=900, env=env)
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
            _build_dataframe(sample, label),
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


def run_human_baseline(sample: BenchmarkSample, label: EvaluationLabel, sample_root: Path) -> BuildExecutionResult:
    repo_root = sample_root / 'baseline_repo'
    original, module_path = instrument_workspace(sample, label, repo_root)
    try:
        return run_build_with_metrics(sample, label, module_path or str(repo_root), repo_root)
    finally:
        restore_instrumentation(sample, module_path, original)


def run_human_stale_check(sample: BenchmarkSample, label: EvaluationLabel, sample_root: Path) -> BuildExecutionResult:
    repo_root = sample_root / 'evolved_repo'
    original, module_path = instrument_workspace(sample, label, repo_root)
    try:
        return run_build_with_metrics(sample, label, module_path or str(repo_root), repo_root)
    finally:
        restore_instrumentation(sample, module_path, original)
