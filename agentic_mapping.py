from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd

from agentic_types import BenchmarkSample, MappingResult


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
    return len(left_set & right_set) / float(len(left_set | right_set))


def _rank(values: List[Tuple[str, float]]) -> List[str]:
    ordered = sorted(values, key=lambda item: (-item[1], item[0]))
    return [name for name, _ in ordered]


def _score_ast(sample: BenchmarkSample) -> Tuple[List[str], Dict[str, Any]]:
    focal_methods = sample.raw_sample.get('focal_class', {}).get('methods', [])
    test_case = sample.raw_sample.get('test_case', {})
    invocations = Counter(test_case.get('invocations', []))
    test_body = test_case.get('body', '')
    body_tokens = Counter(_camel_tokens(test_body))
    scored: List[Tuple[str, float]] = []
    details: Dict[str, Any] = {}

    for method in focal_methods:
        identifier = method.get('identifier', '')
        if not identifier or method.get('constructor'):
            continue
        method_tokens = _camel_tokens(identifier)
        direct_hits = invocations.get(identifier, 0)
        token_overlap = sum(body_tokens.get(token, 0) for token in method_tokens)
        signature_bonus = 1.5 if identifier in test_body else 0.0
        score = (direct_hits * 3.0) + token_overlap + signature_bonus
        scored.append((identifier, score))
        details[identifier] = {
            'direct_hits': direct_hits,
            'token_overlap': token_overlap,
            'signature_bonus': signature_bonus,
            'score': score,
        }
    return _rank(scored), details


def _score_naming(sample: BenchmarkSample) -> Tuple[List[str], Dict[str, Any]]:
    focal_methods = sample.raw_sample.get('focal_class', {}).get('methods', [])
    test_name_tokens = _camel_tokens(sample.test_method_name)
    scored: List[Tuple[str, float]] = []
    details: Dict[str, Any] = {}
    for method in focal_methods:
        identifier = method.get('identifier', '')
        if not identifier or method.get('constructor'):
            continue
        method_tokens = _camel_tokens(identifier)
        score = _jaccard(test_name_tokens, method_tokens)
        if identifier.lower() in sample.test_method_name.lower():
            score += 1.0
        scored.append((identifier, score))
        details[identifier] = {
            'test_name_tokens': test_name_tokens,
            'method_tokens': method_tokens,
            'score': score,
        }
    return _rank(scored), details


def _find_rank(candidates: List[str], value: str) -> int:
    if value in candidates:
        return candidates.index(value) + 1
    return -1


def map_sample(sample: BenchmarkSample) -> MappingResult:
    ast_candidates, ast_details = _score_ast(sample)
    naming_candidates, naming_details = _score_naming(sample)
    ast_prediction = ast_candidates[0] if ast_candidates else None
    naming_prediction = naming_candidates[0] if naming_candidates else None
    ast_rank = _find_rank(ast_candidates, sample.labeled_focal_method)
    naming_rank = _find_rank(naming_candidates, sample.labeled_focal_method)
    return MappingResult(
        sample_id=sample.sample_id,
        project_id=sample.project_id,
        labeled_focal_method=sample.labeled_focal_method,
        ast_prediction=ast_prediction,
        ast_candidates=ast_candidates[:5],
        naming_prediction=naming_prediction,
        naming_candidates=naming_candidates[:5],
        ast_correct=ast_prediction == sample.labeled_focal_method,
        naming_correct=naming_prediction == sample.labeled_focal_method,
        ast_rank=ast_rank if ast_rank > 0 else None,
        naming_rank=naming_rank if naming_rank > 0 else None,
        ast_score_details=ast_details,
        naming_score_details=naming_details,
    )


def evaluate_mapping(samples: List[BenchmarkSample], output_dir: Path) -> List[MappingResult]:
    output_dir.mkdir(parents=True, exist_ok=True)
    results = [map_sample(sample) for sample in samples if sample.runnable]
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


def load_mapping_results(path: Path) -> List[MappingResult]:
    with path.open('r', encoding='utf-8') as handle:
        payload = json.load(handle)
    return [MappingResult(**item) for item in payload]


def _mean(values: List[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / float(len(values)), 4)
