from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List, Tuple

from agentic_config import load_config
from agentic_evolution import generate_evolutions, load_evolutions
from agentic_manifest import build_manifest, load_manifest, save_manifest
from agentic_mapping import evaluate_mapping, load_mapping_results
from agentic_reporting import save_sync_results, summarize_sync_results
from agentic_society import GeminiCliSocietyRunner
from agentic_types import BenchmarkSample, BuildExecutionResult, EvolutionSpec, MappingResult, SyncResult


def _default_config_path() -> Path:
    return Path(__file__).with_name('run_settings.yaml')


def _manifest_paths(config: Dict[str, object]) -> Tuple[Path, Path]:
    output_dir = Path(config['paths']['output_dir'])
    manifest_dir = output_dir / 'manifest'
    return manifest_dir / 'manifest.json', manifest_dir / 'manifest.csv'


def _mapping_paths(config: Dict[str, object]) -> Tuple[Path, Path]:
    output_dir = Path(config['paths']['output_dir'])
    mapping_dir = output_dir / 'mapping'
    return mapping_dir / 'mapping_results.json', mapping_dir / 'mapping_results.csv'


def _evolution_paths(config: Dict[str, object]) -> Tuple[Path, Path]:
    output_dir = Path(config['paths']['output_dir'])
    evolution_dir = output_dir / 'evolution'
    return evolution_dir / 'evolutions.json', evolution_dir / 'evolutions.csv'


def _baseline_row(sample: BenchmarkSample, strategy: str, name: str, baseline: BuildExecutionResult) -> Dict[str, object]:
    prompt_technique = strategy if name == 'human' else ('reference' if name == 'human_reference' else 'evosuite')
    return {
        'sample_id': sample.sample_id,
        'project_id': sample.project_id,
        'Prompt_Technique': prompt_technique,
        'Generator(LLM/EVOSUITE)': name,
        'compilation': baseline.compilation,
        'branch_coverage': baseline.branch_coverage,
        'line_coverage': baseline.line_coverage,
        'method_coverage': baseline.method_coverage,
        'mutation_coverage': baseline.mutation_coverage,
        'Inter_Agent_Loops': 0,
        'Execution_Iterations': 0,
        'Total_Tokens': 0,
        'Intent_Preservation_Score': None,
    }


def cmd_prepare(config: Dict[str, object]) -> None:
    manifest = build_manifest(config)
    manifest_json, manifest_csv = save_manifest(manifest, _manifest_paths(config)[0].parent)
    print('Saved manifest JSON to %s' % manifest_json)
    print('Saved manifest CSV to %s' % manifest_csv)
    runnable = len([sample for sample in manifest if sample.runnable])
    skipped = len(manifest) - runnable
    print('Prepared %s runnable samples and %s skipped samples.' % (runnable, skipped))


def cmd_map(config: Dict[str, object]) -> None:
    manifest_json, _ = _manifest_paths(config)
    manifest = load_manifest(manifest_json)
    results = evaluate_mapping(manifest, _mapping_paths(config)[0].parent)
    print('Evaluated mapping for %s runnable samples.' % len(results))


def cmd_evolve(config: Dict[str, object]) -> None:
    manifest_json, _ = _manifest_paths(config)
    manifest = load_manifest(manifest_json)
    evolutions = generate_evolutions(manifest, config, _evolution_paths(config)[0].parent)
    print('Generated %s evolution specs.' % len(evolutions))


def _load_inputs(config: Dict[str, object]) -> Tuple[List[BenchmarkSample], List[MappingResult], List[EvolutionSpec]]:
    manifest = load_manifest(_manifest_paths(config)[0])
    mapping = load_mapping_results(_mapping_paths(config)[0])
    evolutions = load_evolutions(_evolution_paths(config)[0])
    return manifest, mapping, evolutions


def cmd_sync(config: Dict[str, object]) -> None:
    manifest, mapping_results, evolutions = _load_inputs(config)
    mapping_by_sample = {result.sample_id: result for result in mapping_results}
    evolution_by_sample = {result.sample_id: result for result in evolutions}
    output_dir = Path(config['paths']['output_dir']) / 'sync'
    runner = GeminiCliSocietyRunner(config)
    sync_results: List[SyncResult] = []
    extras: Dict[str, List[Dict[str, object]]] = {'human': [], 'evosuite': [], 'human_reference': []}

    for sample in manifest:
        if not sample.runnable:
            continue
        if sample.sample_id not in mapping_by_sample or sample.sample_id not in evolution_by_sample:
            continue
        for strategy in config['strategies']:
            print('Synchronizing %s with %s' % (sample.sample_id, strategy))
            result, _, baseline_results = runner.run_sample(sample, mapping_by_sample[sample.sample_id], evolution_by_sample[sample.sample_id], strategy)
            sync_results.append(result)
            for name, baseline in baseline_results.items():
                extras.setdefault(name, []).append(_baseline_row(sample, strategy, name, baseline))

    save_sync_results(sync_results, output_dir)
    for name, rows in extras.items():
        if rows:
            with (output_dir / ('%s_results.json' % name)).open('w', encoding='utf-8') as handle:
                json.dump(rows, handle, indent=2)
    print('Saved %s Gemini synchronization results.' % len(sync_results))


def cmd_summarize(config: Dict[str, object]) -> None:
    mapping_results = load_mapping_results(_mapping_paths(config)[0])
    sync_dir = Path(config['paths']['output_dir']) / 'sync'
    sync_payload = json.loads((sync_dir / 'sync_results.json').read_text(encoding='utf-8'))
    sync_results = []
    for row in sync_payload:
        filtered = {key: value for key, value in row.items() if key in SyncResult.__dataclass_fields__}
        sync_results.append(SyncResult(**filtered))
    baseline_rows: List[Dict[str, object]] = []
    for name in ('human', 'evosuite'):
        path = sync_dir / ('%s_results.json' % name)
        if path.exists():
            baseline_rows.extend(json.loads(path.read_text(encoding='utf-8')))
    summary = summarize_sync_results(sync_results, mapping_results, Path(config['paths']['output_dir']) / 'summary', baseline_rows=baseline_rows)
    print('Summary written with sections: %s' % ', '.join(sorted(summary.keys())))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='AgoneTest multi-agent GeminiCLI society')
    parser.add_argument('--config', default=str(_default_config_path()), help='Path to the YAML config.')
    subparsers = parser.add_subparsers(dest='command', required=True)
    for name in ('prepare', 'map', 'evolve', 'sync', 'summarize'):
        subparsers.add_parser(name)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    config = load_config(Path(args.config))
    if args.command == 'prepare':
        cmd_prepare(config)
    elif args.command == 'map':
        cmd_map(config)
    elif args.command == 'evolve':
        cmd_evolve(config)
    elif args.command == 'sync':
        cmd_sync(config)
    elif args.command == 'summarize':
        cmd_summarize(config)
    else:
        parser.error('unknown command')


if __name__ == '__main__':
    main()
