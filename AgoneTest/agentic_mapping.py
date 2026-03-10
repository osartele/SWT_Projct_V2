from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from agentic_types import BenchmarkSample, EvaluationLabel, MappingResult, MethodCandidate


STOP_WORDS = {
    'test', 'should', 'when', 'then', 'given', 'returns', 'return', 'works', 'work',
    'with', 'without', 'for', 'and', 'or', 'uses', 'use'
}


def _camel_tokens(value: str) -> List[str]:
    separated = re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', value or '')
    tokens = re.findall(r'[A-Za-z0-9]+', separated.lower())
    return [token for token in tokens if token not in STOP_WORDS]


def _jaccard(left: List[str], right: List[str]) -> float:
    left_set = set(left)
    right_set = set(right)
    if not left_set and not right_set:
        return 0.0
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / float(len(left_set | right_set))


def _rank(candidates: List[MethodCandidate]) -> List[MethodCandidate]:
    return sorted(
        candidates,
        key=lambda candidate: (-candidate.score, candidate.class_path, candidate.method_signature),
    )


def _mean(values: List[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / float(len(values)), 4)


def _mapper_source_files(mapper_root: Path) -> List[Path]:
    source_root = mapper_root / 'src' / 'main' / 'java'
    return sorted(source_root.rglob('*.java'))


def _mapper_output_root(mapper_root: Path) -> Path:
    return mapper_root / 'out'


def _jdk_version_key(path: Path) -> Tuple[int, ...]:
    digits = re.findall(r'\d+', path.name)
    if not digits:
        return (0,)
    return tuple(int(digit) for digit in digits[:4])


def _java_executable(name: str) -> str:
    suffix = '.exe' if os.name == 'nt' else ''
    preferred_roots: List[Path] = []
    for env_name in ('JAVA_HOME_LAUNCHER', 'JAVA_HOME', 'JAVA_HOME_DEFAULT', 'JAVA_HOME_21', 'JAVA_HOME_17', 'JAVA_HOME_13', 'JAVA_HOME_11', 'JAVA_HOME_8'):
        value = os.getenv(env_name)
        if value:
            preferred_roots.append(Path(value))
    jdks_root = Path.home() / '.jdks'
    if jdks_root.is_dir():
        discovered_roots = sorted(
            [candidate for candidate in jdks_root.iterdir() if candidate.is_dir()],
            key=_jdk_version_key,
            reverse=True,
        )
        preferred_roots.extend(discovered_roots)
    seen: set[str] = set()
    for root in preferred_roots:
        candidate = root / 'bin' / (name + suffix)
        candidate_key = str(candidate).lower()
        if candidate_key in seen:
            continue
        seen.add(candidate_key)
        if candidate.is_file() and _jdk_version_key(root)[0] >= 8:
            return str(candidate)
    discovered = shutil.which(name + suffix) or shutil.which(name)
    if discovered:
        return discovered
    raise RuntimeError('missing_java_executable:%s' % name)

def _ensure_mapper_cli_compiled(config: Dict[str, Any]) -> Path:
    mapper_root = Path(config['paths']['mapper_cli'])
    source_files = _mapper_source_files(mapper_root)
    if not source_files:
        raise RuntimeError('mapper_cli_sources_missing:%s' % mapper_root)
    output_root = _mapper_output_root(mapper_root)
    marker = output_root / 'compile.stamp'
    if marker.exists() and all(source.stat().st_mtime <= marker.stat().st_mtime for source in source_files):
        return output_root

    output_root.mkdir(parents=True, exist_ok=True)
    command = [_java_executable('javac'), '-d', str(output_root), *[str(source) for source in source_files]]
    result = subprocess.run(command, cwd=str(mapper_root), capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or 'mapper_cli_compile_failed')
    marker.write_text('compiled', encoding='utf-8')
    return output_root


def _invoke_ast_mapper(sample: BenchmarkSample, config: Dict[str, Any]) -> Dict[str, Any]:
    if sample.repo_path is None or sample.build_metadata is None:
        return {'ast_candidates': [], 'method_index': [], 'analysis': {'mapper_error': 'sample_not_runnable'}}
    output_root = _ensure_mapper_cli_compiled(config)
    repo_root = sample.repo_path.resolve()
    module_root = Path(sample.build_metadata.module_path).resolve()
    top_k = int(config['mapping'].get('top_k', 5))
    scope = str(config['mapping'].get('scope', 'module_then_repo'))
    command = [
        _java_executable('java'),
        '-cp',
        str(output_root),
        'agone.mapper.MapperCli',
        str(repo_root),
        str(module_root),
        sample.test_class_path,
        sample.test_method_name,
        str(top_k),
        scope,
    ]
    result = subprocess.run(command, cwd=str(repo_root), capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or 'mapper_cli_failed')
    return json.loads(result.stdout)


def _method_candidate(payload: Dict[str, Any], score: Optional[float] = None, confidence: Optional[float] = None, evidence: Optional[Dict[str, Any]] = None) -> MethodCandidate:
    return MethodCandidate(
        class_name=payload.get('class_name', ''),
        class_fqn=payload.get('class_fqn'),
        class_path=payload.get('class_path', ''),
        method_name=payload.get('method_name', ''),
        method_signature=payload.get('method_signature', ''),
        score=float(payload.get('score', score if score is not None else 0.0) or 0.0),
        confidence=float(payload.get('confidence', confidence if confidence is not None else 0.0) or 0.0),
        evidence=dict(payload.get('evidence', evidence if evidence is not None else {})),
        parameter_count=int(payload.get('parameter_count', 0) or 0),
        static_method=bool(payload.get('static_method', False)),
    )


def _score_naming(sample: BenchmarkSample, method_index: List[MethodCandidate], top_k: int) -> Tuple[List[MethodCandidate], Dict[str, Any]]:
    test_name_tokens = _camel_tokens(sample.test_method_name)
    scored: List[MethodCandidate] = []
    details: Dict[str, Any] = {}
    for method in method_index:
        method_tokens = _camel_tokens(method.method_name)
        score = _jaccard(test_name_tokens, method_tokens)
        if method.method_name.lower() in sample.test_method_name.lower():
            score += 1.0
        candidate = MethodCandidate(
            class_name=method.class_name,
            class_fqn=method.class_fqn,
            class_path=method.class_path,
            method_name=method.method_name,
            method_signature=method.method_signature,
            score=round(score, 4),
            confidence=0.0,
            evidence={
                'test_name_tokens': test_name_tokens,
                'method_tokens': method_tokens,
                'score': round(score, 4),
            },
            parameter_count=method.parameter_count,
            static_method=method.static_method,
        )
        scored.append(candidate)
        details['%s#%s' % (method.class_path, method.method_signature)] = candidate.evidence
    ranked = _rank(scored)
    top_score = ranked[0].score if ranked else 0.0
    normalized: List[MethodCandidate] = []
    for candidate in ranked[:top_k]:
        normalized.append(
            MethodCandidate(
                class_name=candidate.class_name,
                class_fqn=candidate.class_fqn,
                class_path=candidate.class_path,
                method_name=candidate.method_name,
                method_signature=candidate.method_signature,
                score=candidate.score,
                confidence=round(candidate.score / top_score, 4) if top_score > 0 else 0.0,
                evidence=candidate.evidence,
                parameter_count=candidate.parameter_count,
                static_method=candidate.static_method,
            )
        )
    return normalized, details


def _candidate_matches(candidate: MethodCandidate, label: EvaluationLabel) -> bool:
    if candidate.class_path != label.focal_class_path:
        return False
    if candidate.method_name != label.labeled_focal_method:
        return False
    if label.labeled_focal_signature and candidate.method_signature:
        label_signature = label.labeled_focal_signature.strip()
        candidate_signature = candidate.method_signature.strip()
        if label_signature != candidate_signature:
            return candidate.method_name == label.labeled_focal_method
    return True


def _find_rank(candidates: List[MethodCandidate], label: EvaluationLabel) -> Optional[int]:
    for index, candidate in enumerate(candidates, start=1):
        if _candidate_matches(candidate, label):
            return index
    return None


def _prediction_fields(candidate: Optional[MethodCandidate]) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str], float, Dict[str, Any]]:
    if candidate is None:
        return None, None, None, None, 0.0, {}
    return (
        candidate.method_name,
        candidate.method_signature,
        candidate.class_path,
        candidate.class_fqn,
        candidate.confidence,
        candidate.evidence,
    )


def map_sample(sample: BenchmarkSample, label: EvaluationLabel, config: Dict[str, Any]) -> MappingResult:
    top_k = int(config['mapping'].get('top_k', 5))
    backend = str(config['mapping'].get('backend', 'java_sidecar'))
    if backend != 'java_sidecar':
        raise RuntimeError('unsupported_mapping_backend:%s' % backend)

    try:
        mapper_payload = _invoke_ast_mapper(sample, config)
        ast_candidates = [_method_candidate(candidate) for candidate in mapper_payload.get('ast_candidates', [])]
        method_index = [_method_candidate(candidate) for candidate in mapper_payload.get('method_index', [])]
        ast_evidence = dict(mapper_payload.get('analysis', {}))
    except Exception as error:
        ast_candidates = []
        method_index = []
        ast_evidence = {'mapper_error': str(error)}

    naming_candidates, naming_evidence = _score_naming(sample, method_index, top_k)

    ast_prediction = ast_candidates[0] if ast_candidates else None
    naming_prediction = naming_candidates[0] if naming_candidates else None
    ast_rank = _find_rank(ast_candidates, label)
    naming_rank = _find_rank(naming_candidates, label)

    ast_prediction_name, ast_signature, ast_class_path, ast_class_fqn, ast_confidence, ast_prediction_evidence = _prediction_fields(ast_prediction)
    naming_prediction_name, naming_signature, naming_class_path, naming_class_fqn, naming_confidence, naming_prediction_evidence = _prediction_fields(naming_prediction)
    if ast_prediction_evidence:
        ast_evidence = {'backend': ast_evidence, 'prediction': ast_prediction_evidence}

    return MappingResult(
        sample_id=sample.sample_id,
        project_id=sample.project_id,
        oracle_focal_class_path=label.focal_class_path,
        oracle_focal_method=label.labeled_focal_method,
        oracle_focal_signature=label.labeled_focal_signature,
        ast_prediction=ast_prediction_name,
        ast_prediction_signature=ast_signature,
        ast_prediction_class_path=ast_class_path,
        ast_prediction_class_fqn=ast_class_fqn,
        ast_candidates=ast_candidates,
        naming_prediction=naming_prediction_name,
        naming_prediction_signature=naming_signature,
        naming_prediction_class_path=naming_class_path,
        naming_prediction_class_fqn=naming_class_fqn,
        naming_candidates=naming_candidates,
        ast_correct=bool(ast_prediction and _candidate_matches(ast_prediction, label)),
        naming_correct=bool(naming_prediction and _candidate_matches(naming_prediction, label)),
        ast_rank=ast_rank,
        naming_rank=naming_rank,
        ast_confidence=ast_confidence,
        naming_confidence=naming_confidence,
        ast_evidence=ast_evidence,
        naming_evidence={
            'baseline': naming_evidence,
            'prediction': naming_prediction_evidence,
        },
    )


def evaluate_mapping(samples: List[BenchmarkSample], labels: List[EvaluationLabel], config: Dict[str, Any], output_dir: Path) -> List[MappingResult]:
    output_dir.mkdir(parents=True, exist_ok=True)
    labels_by_sample = {label.sample_id: label for label in labels}
    results = [map_sample(sample, labels_by_sample[sample.sample_id], config) for sample in samples if sample.runnable and sample.sample_id in labels_by_sample]
    rows = [result.to_dict() for result in results]
    with (output_dir / 'mapping_results.json').open('w', encoding='utf-8') as handle:
        json.dump(rows, handle, indent=2)
    pd.DataFrame(rows).to_csv(output_dir / 'mapping_results.csv', index=False)

    summary = {
        'rq1_ast_top1_accuracy': _mean([1.0 if result.ast_correct else 0.0 for result in results]),
        'rq1_naming_top1_accuracy': _mean([1.0 if result.naming_correct else 0.0 for result in results]),
        'rq1_ast_top3_accuracy': _mean([1.0 if result.ast_rank is not None and result.ast_rank <= 3 else 0.0 for result in results]),
        'rq1_naming_top3_accuracy': _mean([1.0 if result.naming_rank is not None and result.naming_rank <= 3 else 0.0 for result in results]),
        'rq1_ast_mrr': _mean([1.0 / result.ast_rank if result.ast_rank else 0.0 for result in results]),
        'rq1_naming_mrr': _mean([1.0 / result.naming_rank if result.naming_rank else 0.0 for result in results]),
    }
    with (output_dir / 'mapping_summary.json').open('w', encoding='utf-8') as handle:
        json.dump(summary, handle, indent=2)
    return results


def _load_candidates(payload: List[Dict[str, Any]]) -> List[MethodCandidate]:
    return [_method_candidate(item) for item in payload]


def load_mapping_results(path: Path) -> List[MappingResult]:
    with path.open('r', encoding='utf-8') as handle:
        payload = json.load(handle)
    results: List[MappingResult] = []
    for item in payload:
        results.append(
            MappingResult(
                sample_id=item['sample_id'],
                project_id=item['project_id'],
                oracle_focal_class_path=item['oracle_focal_class_path'],
                oracle_focal_method=item['oracle_focal_method'],
                oracle_focal_signature=item['oracle_focal_signature'],
                ast_prediction=item.get('ast_prediction'),
                ast_prediction_signature=item.get('ast_prediction_signature'),
                ast_prediction_class_path=item.get('ast_prediction_class_path'),
                ast_prediction_class_fqn=item.get('ast_prediction_class_fqn'),
                ast_candidates=_load_candidates(item.get('ast_candidates', [])),
                naming_prediction=item.get('naming_prediction'),
                naming_prediction_signature=item.get('naming_prediction_signature'),
                naming_prediction_class_path=item.get('naming_prediction_class_path'),
                naming_prediction_class_fqn=item.get('naming_prediction_class_fqn'),
                naming_candidates=_load_candidates(item.get('naming_candidates', [])),
                ast_correct=item['ast_correct'],
                naming_correct=item['naming_correct'],
                ast_rank=item.get('ast_rank'),
                naming_rank=item.get('naming_rank'),
                ast_confidence=float(item.get('ast_confidence', 0.0) or 0.0),
                naming_confidence=float(item.get('naming_confidence', 0.0) or 0.0),
                ast_evidence=item.get('ast_evidence', {}),
                naming_evidence=item.get('naming_evidence', {}),
            )
        )
    return results

