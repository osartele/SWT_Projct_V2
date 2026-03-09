from __future__ import annotations

import difflib
import json
import re
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from agentic_types import BenchmarkSample, EvolutionSpec


def _predicate_inversion(body: str) -> Optional[str]:
    replacements = [('==', '!='), ('!=', '=='), ('>=', '<'), ('<=', '>'), ('>', '<='), ('<', '>=')]
    for old, new in replacements:
        if old in body:
            return body.replace(old, new, 1)
    return None


def _boundary_shift(body: str) -> Optional[str]:
    match = re.search(r'(?<![\w.])(-?\d+)(?![\w.])', body)
    if not match:
        return None
    value = int(match.group(1))
    replacement = str(value + 1 if value >= 0 else value - 1)
    return body[: match.start(1)] + replacement + body[match.end(1) :]


def _return_value_change(body: str) -> Optional[str]:
    for old, new in [('return true;', 'return false;'), ('return false;', 'return true;')]:
        if old in body:
            return body.replace(old, new, 1)
    numeric_return = re.search(r'return\s+(-?\d+)\s*;', body)
    if numeric_return:
        value = int(numeric_return.group(1))
        return body.replace(numeric_return.group(0), 'return %s;' % (value + 1), 1)
    return None


def _exception_path_change(body: str) -> Optional[str]:
    brace = body.find('{')
    if brace == -1:
        return None
    insertion = '\n        if (System.currentTimeMillis() >= 0) { throw new IllegalStateException("Synthetic evolution"); }\n'
    return body[: brace + 1] + insertion + body[brace + 1 :]


OPERATORS = {
    'predicate_inversion': _predicate_inversion,
    'boundary_shift': _boundary_shift,
    'return_value_change': _return_value_change,
    'exception_path_change': _exception_path_change,
}


def create_evolution(sample: BenchmarkSample, operator_names: List[str]) -> EvolutionSpec:
    original_body = sample.focal_method_body or ''
    validation_notes: List[str] = []
    evolved_body = None
    used_operator = None
    for operator_name in operator_names:
        evolved_body = OPERATORS[operator_name](original_body)
        if evolved_body and evolved_body != original_body:
            used_operator = operator_name
            break
    if evolved_body is None:
        used_operator = 'no_op'
        evolved_body = original_body
        validation_notes.append('no_supported_operator_matched_method_body')

    diff = ''.join(
        difflib.unified_diff(
            original_body.splitlines(True),
            evolved_body.splitlines(True),
            fromfile='original',
            tofile='evolved',
        )
    )
    static_validation_passed = used_operator != 'no_op' and bool(diff.strip())
    if static_validation_passed:
        validation_notes.append('static_diff_created')
    return EvolutionSpec(
        sample_id=sample.sample_id,
        project_id=sample.project_id,
        operator=used_operator,
        method_identifier=sample.labeled_focal_method,
        method_signature=sample.labeled_focal_signature,
        original_body=original_body,
        evolved_body=evolved_body,
        target_file=sample.focal_class_path,
        diff=diff,
        replaced_exact_body=True,
        static_validation_passed=static_validation_passed,
        validation_notes=validation_notes,
    )


def generate_evolutions(samples: List[BenchmarkSample], config: Dict[str, object], output_dir: Path) -> List[EvolutionSpec]:
    output_dir.mkdir(parents=True, exist_ok=True)
    operators = list(config['evolution']['operators'])
    evolutions = [create_evolution(sample, operators) for sample in samples if sample.runnable]
    rows = [evolution.to_dict() for evolution in evolutions]
    with (output_dir / 'evolutions.json').open('w', encoding='utf-8') as handle:
        json.dump(rows, handle, indent=2)
    pd.DataFrame(rows).to_csv(output_dir / 'evolutions.csv', index=False)
    return evolutions


def load_evolutions(path: Path) -> List[EvolutionSpec]:
    with path.open('r', encoding='utf-8') as handle:
        payload = json.load(handle)
    return [EvolutionSpec(**item) for item in payload]
