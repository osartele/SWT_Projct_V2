import tempfile
import unittest
from pathlib import Path

from agentic_reporting import summarize_sync_results
from agentic_types import MappingResult, MethodCandidate, SyncResult


class ReportingTests(unittest.TestCase):
    def test_summary_includes_context_policy_and_baseline_rows(self):
        sync_result = SyncResult(
            sample_id='sample',
            project_id='1',
            generator='gemini-cli',
            prompt_technique='regenerative',
            context_policy='ast_predicted',
            mapped_focal_method='add',
            mapped_focal_signature='int add(int a, int b)',
            mapped_focal_class_path='src/main/java/Calculator.java',
            mapping_correct=True,
            mapping_confidence=0.9,
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
        candidate = MethodCandidate(
            class_name='Calculator',
            class_fqn='example.Calculator',
            class_path='src/main/java/Calculator.java',
            method_name='add',
            method_signature='int add(int a, int b)',
            score=1.0,
            confidence=1.0,
            evidence={},
        )
        mapping_result = MappingResult(
            sample_id='sample',
            project_id='1',
            oracle_focal_class_path='src/main/java/Calculator.java',
            oracle_focal_method='add',
            oracle_focal_signature='int add(int a, int b)',
            ast_prediction='add',
            ast_prediction_signature='int add(int a, int b)',
            ast_prediction_class_path='src/main/java/Calculator.java',
            ast_prediction_class_fqn='example.Calculator',
            ast_candidates=[candidate],
            naming_prediction='add',
            naming_prediction_signature='int add(int a, int b)',
            naming_prediction_class_path='src/main/java/Calculator.java',
            naming_prediction_class_fqn='example.Calculator',
            naming_candidates=[candidate],
            ast_correct=True,
            naming_correct=True,
            ast_rank=1,
            naming_rank=1,
            ast_confidence=1.0,
            naming_confidence=1.0,
            ast_evidence={},
            naming_evidence={},
        )
        baseline_rows = [
            {
                'sample_id': 'sample',
                'project_id': '1',
                'Prompt_Technique': 'regenerative',
                'Context_Policy': 'ast_predicted',
                'Generator(LLM/EVOSUITE)': 'human',
                'compilation': 0,
                'branch_coverage': 10.0,
                'line_coverage': 15.0,
                'method_coverage': 20.0,
                'mutation_coverage': 5.0,
                'Inter_Agent_Loops': 0,
                'Execution_Iterations': 0,
                'Total_Tokens': 0,
                'Mapping_Correct': None,
                'Mapping_Confidence': None,
                'Intent_Preservation_Score': None,
            }
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            summary = summarize_sync_results([sync_result], [mapping_result], Path(temp_dir), baseline_rows=baseline_rows)
        generators = {row['Generator(LLM/EVOSUITE)'] for row in summary['rq2']}
        self.assertIn('gemini-cli', generators)
        self.assertIn('human', generators)
        self.assertTrue(all('Context_Policy' in row for row in summary['rq2']))


if __name__ == '__main__':
    unittest.main()
