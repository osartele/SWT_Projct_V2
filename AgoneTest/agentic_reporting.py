from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from agentic_types import MappingResult, SyncResult


def save_sync_results(results: List[SyncResult], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = [result.to_dict() for result in results]
    with (output_dir / 'sync_results.json').open('w', encoding='utf-8') as handle:
        json.dump(rows, handle, indent=2)
    pd.DataFrame(rows).to_csv(output_dir / 'sync_results.csv', index=False)


def summarize_sync_results(results: List[SyncResult], mapping_results: List[MappingResult], output_dir: Path, baseline_rows: Optional[List[Dict[str, object]]] = None) -> Dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = [result.to_dict() for result in results]
    if baseline_rows:
        rows.extend(baseline_rows)
    frame = pd.DataFrame(rows)
    summary: Dict[str, object] = {}
    if not frame.empty:
        grouped = frame.groupby(['Generator(LLM/EVOSUITE)', 'Prompt_Technique'], dropna=False).agg(
            Compilation=('compilation', 'mean'),
            Branch_Coverage=('branch_coverage', 'mean'),
            Line_Coverage=('line_coverage', 'mean'),
            Method_Coverage=('method_coverage', 'mean'),
            Mutation_Coverage=('mutation_coverage', 'mean'),
            Inter_Agent_Loops=('Inter_Agent_Loops', 'mean'),
            Execution_Iterations=('Execution_Iterations', 'mean'),
            Total_Tokens=('Total_Tokens', 'mean'),
            Intent_Preservation=('Intent_Preservation_Score', 'mean'),
        ).reset_index()
        grouped.to_csv(output_dir / 'sync_summary.csv', index=False)
        summary['sync_summary'] = grouped.to_dict(orient='records')
        summary['rq2'] = grouped[['Generator(LLM/EVOSUITE)', 'Prompt_Technique', 'Compilation', 'Line_Coverage', 'Branch_Coverage', 'Method_Coverage', 'Mutation_Coverage']].to_dict(orient='records')
        summary['rq3'] = grouped[['Generator(LLM/EVOSUITE)', 'Prompt_Technique', 'Intent_Preservation', 'Mutation_Coverage']].to_dict(orient='records')
        summary['rq4'] = grouped[['Generator(LLM/EVOSUITE)', 'Prompt_Technique', 'Inter_Agent_Loops', 'Execution_Iterations', 'Total_Tokens']].to_dict(orient='records')

    rq1 = {
        'ast_top1_accuracy': _mean([1.0 if result.ast_correct else 0.0 for result in mapping_results]),
        'naming_top1_accuracy': _mean([1.0 if result.naming_correct else 0.0 for result in mapping_results]),
        'ast_top3_accuracy': _mean([1.0 if result.ast_rank is not None and result.ast_rank <= 3 else 0.0 for result in mapping_results]),
        'naming_top3_accuracy': _mean([1.0 if result.naming_rank is not None and result.naming_rank <= 3 else 0.0 for result in mapping_results]),
        'ast_mrr': _mean([1.0 / result.ast_rank if result.ast_rank else 0.0 for result in mapping_results]),
        'naming_mrr': _mean([1.0 / result.naming_rank if result.naming_rank else 0.0 for result in mapping_results]),
    }
    summary['rq1'] = rq1
    with (output_dir / 'rq_summary.json').open('w', encoding='utf-8') as handle:
        json.dump(summary, handle, indent=2)
    return summary


def _mean(values: List[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / float(len(values)), 4)
