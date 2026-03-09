import tempfile
import unittest
from pathlib import Path

from agentic_reporting import summarize_sync_results
from agentic_types import MappingResult, SyncResult


class ReportingTests(unittest.TestCase):
    def test_summary_includes_baseline_rows(self):
        sync_result = SyncResult(
            sample_id='sample',
            project_id='1',
            generator='gemini-cli',
            prompt_technique='regenerative',
            mapped_focal_method='add',
            mapping_correct=True,
            evolution_operator='return_value_change',
            converged=True,
            compilation=1,
            branch_coverage=80.0,
            line_coverage=85.0,
            method_coverage=90.0,
            mutation_coverage=70.0,
            inter_agent_loops=1,
            execution_iterations=2,
            semantic_rejections=1,
            generator_tokens=10,
            critic_tokens=5,
            analyst_tokens=3,
            total_tokens=18,
            regression_blindness_flag=False,
            intent_target_agreement=1.0,
            intent_assertion_similarity=1.0,
            intent_fixture_similarity=1.0,
            intent_pit_component=1.0,
            intent_preservation_score=1.0,
            convergence_path='critic_approved_execution_pass',
            blackboard_path='blackboard.json',
            transcript_path='agent_turns.json',
            error_message=None,
        )
        mapping_result = MappingResult(
            sample_id='sample',
            project_id='1',
            labeled_focal_method='add',
            ast_prediction='add',
            ast_candidates=['add'],
            naming_prediction='add',
            naming_candidates=['add'],
            ast_correct=True,
            naming_correct=True,
            ast_rank=1,
            naming_rank=1,
            ast_score_details={},
            naming_score_details={},
        )
        baseline_rows = [
            {
                'sample_id': 'sample',
                'project_id': '1',
                'Prompt_Technique': 'regenerative',
                'Generator(LLM/EVOSUITE)': 'human',
                'compilation': 0,
                'branch_coverage': 10.0,
                'line_coverage': 15.0,
                'method_coverage': 20.0,
                'mutation_coverage': 5.0,
                'Inter_Agent_Loops': 0,
                'Execution_Iterations': 0,
                'Total_Tokens': 0,
                'Intent_Preservation_Score': None,
            }
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            summary = summarize_sync_results([sync_result], [mapping_result], Path(temp_dir), baseline_rows=baseline_rows)
        generators = {row['Generator(LLM/EVOSUITE)'] for row in summary['rq2']}
        self.assertIn('gemini-cli', generators)
        self.assertIn('human', generators)


if __name__ == '__main__':
    unittest.main()
