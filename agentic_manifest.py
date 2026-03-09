from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd

import gradleLib
import mavenLib
import utils
from agentic_types import BenchmarkSample, BuildMetadata


def _iter_dataset_files(dataset_dir: Path) -> Iterable[Path]:
    for path in sorted(dataset_dir.glob('*.json')):
        if path.is_file():
            yield path


def _load_json(path: Path) -> Dict[str, Any]:
    with path.open('r', encoding='utf-8') as handle:
        return json.load(handle)


def _infer_project_id(path: Path, payload: Dict[str, Any]) -> str:
    repo_info = payload.get('repository', {})
    repo_id = repo_info.get('repo_id')
    if repo_id is not None:
        return str(repo_id)
    return path.stem.split('_')[0]


def _find_build_root(repo_path: Path, relative_path: str) -> Tuple[Optional[Path], Optional[str]]:
    target = repo_path / Path(relative_path)
    current = target.parent
    while current.exists() and current != repo_path.parent:
        if (current / 'pom.xml').exists():
            return current, 'Maven'
        if (current / 'build.gradle').exists() or (current / 'build.gradle.kts').exists():
            return current, 'Gradle'
        if current == repo_path:
            break
        current = current.parent
    if (repo_path / 'pom.xml').exists():
        return repo_path, 'Maven'
    if (repo_path / 'build.gradle').exists() or (repo_path / 'build.gradle.kts').exists():
        return repo_path, 'Gradle'
    return None, None


def _extract_build_metadata(build_root: Path, build_system: str) -> BuildMetadata:
    if build_system == 'Maven':
        java_version, junit_version, testng_version = mavenLib.extract_test_and_java_version_maven(str(build_root))
        compiler_version = mavenLib.extract_maven_version(str(build_root))
    else:
        java_version, junit_version, testng_version, compiler_version = gradleLib.extract_info_build_gradle(
            str(build_root),
            True,
        )
    has_mockito = utils.verify_mockito(build_system, str(build_root))
    return BuildMetadata(
        build_system=build_system.lower(),
        module_path=str(build_root),
        java_version=java_version or '1.8',
        junit_version=junit_version,
        testng_version=testng_version,
        compiler_version=compiler_version,
        has_mockito=bool(has_mockito),
    )


def build_manifest(config: Dict[str, Any]) -> List[BenchmarkSample]:
    dataset_dir = Path(config['paths']['dataset_dir'])
    repos_dir = Path(config['paths']['repos_dir'])
    max_samples = config['filters']['max_samples']
    project_filters = set(str(item) for item in config['filters'].get('project_ids', []))
    sample_filters = set(str(item) for item in config['filters'].get('sample_ids', []))

    manifest: List[BenchmarkSample] = []
    for dataset_path in _iter_dataset_files(dataset_dir):
        if max_samples is not None and len(manifest) >= int(max_samples):
            break
        payload = _load_json(dataset_path)
        project_id = _infer_project_id(dataset_path, payload)
        sample_id = dataset_path.stem
        if project_filters and project_id not in project_filters:
            continue
        if sample_filters and sample_id not in sample_filters:
            continue

        repo_path = repos_dir / project_id
        focal = payload.get('focal_class', {})
        test_class = payload.get('test_class', {})
        test_case = payload.get('test_case', {})
        focal_method = payload.get('focal_method', {})

        build_metadata = None
        runnable = False
        skip_reason = None

        if repo_path.exists():
            build_root, build_system = _find_build_root(repo_path, focal.get('file', ''))
            if build_root is not None and build_system is not None:
                build_metadata = _extract_build_metadata(build_root, build_system)
                runnable = True
            else:
                skip_reason = 'no_supported_build_file'
        else:
            skip_reason = 'missing_repo'

        manifest.append(
            BenchmarkSample(
                sample_id=sample_id,
                dataset_path=dataset_path,
                project_id=project_id,
                repo_path=repo_path if repo_path.exists() else None,
                focal_class_name=focal.get('identifier', ''),
                focal_class_path=focal.get('file', ''),
                test_class_name=test_class.get('identifier', ''),
                test_class_path=test_class.get('file', ''),
                test_method_name=test_case.get('identifier', ''),
                labeled_focal_method=focal_method.get('identifier', ''),
                labeled_focal_signature=focal_method.get('signature', ''),
                build_metadata=build_metadata,
                runnable=runnable,
                skip_reason=skip_reason,
                repository_url=payload.get('repository', {}).get('url'),
                focal_method_body=focal_method.get('body', ''),
                raw_sample=payload,
            )
        )
    return manifest


def save_manifest(manifest: List[BenchmarkSample], output_dir: Path) -> Tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_json = output_dir / 'manifest.json'
    manifest_csv = output_dir / 'manifest.csv'
    rows = [sample.to_dict() for sample in manifest]
    with manifest_json.open('w', encoding='utf-8') as handle:
        json.dump(rows, handle, indent=2)
    pd.DataFrame(rows).to_csv(manifest_csv, index=False)
    return manifest_json, manifest_csv


def load_manifest(path: Path) -> List[BenchmarkSample]:
    payload = _load_json(path)
    manifest: List[BenchmarkSample] = []
    for item in payload:
        build_metadata = item.get('build_metadata')
        manifest.append(
            BenchmarkSample(
                sample_id=item['sample_id'],
                dataset_path=Path(item['dataset_path']),
                project_id=item['project_id'],
                repo_path=Path(item['repo_path']) if item.get('repo_path') else None,
                focal_class_name=item['focal_class_name'],
                focal_class_path=item['focal_class_path'],
                test_class_name=item['test_class_name'],
                test_class_path=item['test_class_path'],
                test_method_name=item['test_method_name'],
                labeled_focal_method=item['labeled_focal_method'],
                labeled_focal_signature=item['labeled_focal_signature'],
                build_metadata=BuildMetadata(**build_metadata) if build_metadata else None,
                runnable=item['runnable'],
                skip_reason=item.get('skip_reason'),
                repository_url=item.get('repository_url'),
                focal_method_body=item.get('focal_method_body', ''),
                raw_sample=item.get('raw_sample', {}),
            )
        )
    return manifest
