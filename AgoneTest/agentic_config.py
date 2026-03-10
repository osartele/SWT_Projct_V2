from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict

import yaml


DEFAULT_CONFIG = {
    'paths': {
        'dataset_dir': '../classes2test',
        'repos_dir': '../repos',
        'output_dir': './output_agentic',
        'workspace_dir': './workspaces_agentic',
        'mapper_cli': './mapper_cli',
    },
    'filters': {
        'project_ids': [],
        'sample_ids': [],
        'max_samples': None,
    },
    'mapping': {
        'backend': 'java_sidecar',
        'scope': 'module_then_repo',
        'top_k': 5,
    },
    'agents': {
        'generator': {'model': 'gemini-cli', 'command': 'gemini', 'temperature': 0},
        'critic': {'model': 'gemini-cli', 'command': 'gemini', 'temperature': 0},
        'analyst': {'model': 'gemini-cli', 'command': 'gemini', 'temperature': 0},
    },
    'strategies': ['regenerative', 'iterative_healing'],
    'sync': {
        'context_policy': 'ast_predicted',
    },
    'limits': {
        'max_semantic_rejections': 3,
        'max_execution_iterations': 5,
        'max_failure_log_chars': 8000,
    },
    'evolution': {
        'operators': [
            'predicate_inversion',
            'boundary_shift',
            'return_value_change',
            'exception_path_change',
        ]
    },
    'baselines': {'run_human': True, 'run_evosuite': True},
}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(config_path: Path) -> Dict[str, Any]:
    with config_path.open('r', encoding='utf-8') as handle:
        loaded = yaml.safe_load(handle) or {}
    config = _deep_merge(DEFAULT_CONFIG, loaded)
    for key, value in config['paths'].items():
        config['paths'][key] = str((config_path.parent / value).resolve())
    return config
