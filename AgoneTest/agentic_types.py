from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


def _serialize(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if is_dataclass(value):
        return {key: _serialize(item) for key, item in asdict(value).items()}
    return value


@dataclass
class BuildMetadata:
    build_system: str
    module_path: str
    java_version: str
    junit_version: Optional[str]
    testng_version: Optional[str]
    compiler_version: Optional[str]
    has_mockito: bool

    def to_dict(self) -> Dict[str, Any]:
        return _serialize(self)


@dataclass
class BenchmarkSample:
    sample_id: str
    dataset_path: Path
    project_id: str
    repo_path: Optional[Path]
    test_class_name: str
    test_class_path: str
    test_method_name: str
    build_metadata: Optional[BuildMetadata]
    runnable: bool
    skip_reason: Optional[str]
    repository_url: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return _serialize(self)


@dataclass
class EvaluationLabel:
    sample_id: str
    project_id: str
    focal_class_name: str
    focal_class_path: str
    labeled_focal_method: str
    labeled_focal_signature: str
    focal_method_body: str
    raw_sample: Dict[str, Any] = field(repr=False)

    def to_dict(self) -> Dict[str, Any]:
        return _serialize(self)


@dataclass
class MethodCandidate:
    class_name: str
    class_fqn: Optional[str]
    class_path: str
    method_name: str
    method_signature: str
    score: float
    confidence: float
    evidence: Dict[str, Any]
    parameter_count: int = 0
    static_method: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return _serialize(self)


@dataclass
class MappingResult:
    sample_id: str
    project_id: str
    oracle_focal_class_path: str
    oracle_focal_method: str
    oracle_focal_signature: str
    ast_prediction: Optional[str]
    ast_prediction_signature: Optional[str]
    ast_prediction_class_path: Optional[str]
    ast_prediction_class_fqn: Optional[str]
    ast_candidates: List[MethodCandidate]
    naming_prediction: Optional[str]
    naming_prediction_signature: Optional[str]
    naming_prediction_class_path: Optional[str]
    naming_prediction_class_fqn: Optional[str]
    naming_candidates: List[MethodCandidate]
    ast_correct: bool
    naming_correct: bool
    ast_rank: Optional[int]
    naming_rank: Optional[int]
    ast_confidence: float
    naming_confidence: float
    ast_evidence: Dict[str, Any]
    naming_evidence: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return _serialize(self)


@dataclass
class EvolutionSpec:
    sample_id: str
    project_id: str
    target_class_name: str
    operator: str
    method_identifier: str
    method_signature: str
    original_body: str
    evolved_body: str
    target_file: str
    diff: str
    replaced_exact_body: bool
    static_validation_passed: bool
    validation_notes: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return _serialize(self)


@dataclass
class AgentTurn:
    sample_id: str
    strategy: str
    execution_iteration: int
    semantic_iteration: int
    agent_role: str
    message_type: str
    prompt_text: str
    response_text: str
    prompt_tokens: int
    completion_tokens: int
    wall_clock_seconds: float
    verdict: Optional[str] = None
    notes: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return _serialize(self)


@dataclass
class BuildExecutionResult:
    success: bool
    stdout: str
    stderr: str
    summary: str
    compilation: int
    branch_coverage: Optional[float]
    line_coverage: Optional[float]
    method_coverage: Optional[float]
    mutation_coverage: Optional[float]

    def to_dict(self) -> Dict[str, Any]:
        return _serialize(self)


@dataclass
class SyncResult:
    sample_id: str
    project_id: str
    generator: str
    prompt_technique: str
    context_policy: str
    mapped_focal_method: Optional[str]
    mapped_focal_signature: Optional[str]
    mapped_focal_class_path: Optional[str]
    mapping_correct: bool
    mapping_confidence: float
    evolution_operator: str
    converged: bool
    compilation: int
    branch_coverage: Optional[float]
    line_coverage: Optional[float]
    method_coverage: Optional[float]
    mutation_coverage: Optional[float]
    inter_agent_loops: int
    execution_iterations: int
    semantic_rejections: int
    generator_tokens: int
    critic_tokens: int
    analyst_tokens: int
    total_tokens: int
    regression_blindness_flag: bool
    intent_target_agreement: float
    intent_assertion_similarity: float
    intent_fixture_similarity: float
    intent_pit_component: float
    intent_preservation_score: float
    convergence_path: str
    blackboard_path: Optional[str]
    transcript_path: Optional[str]
    error_message: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        payload = _serialize(self)
        payload['Generator(LLM/EVOSUITE)'] = self.generator
        payload['Prompt_Technique'] = self.prompt_technique
        payload['Context_Policy'] = self.context_policy
        payload['Mapped_Focal_Method'] = self.mapped_focal_method
        payload['Mapped_Focal_Signature'] = self.mapped_focal_signature
        payload['Mapped_Focal_Class_Path'] = self.mapped_focal_class_path
        payload['Mapping_Correct'] = int(self.mapping_correct)
        payload['Mapping_Confidence'] = self.mapping_confidence
        payload['Evolution_Operator'] = self.evolution_operator
        payload['Converged'] = int(self.converged)
        payload['Inter_Agent_Loops'] = self.inter_agent_loops
        payload['Execution_Iterations'] = self.execution_iterations
        payload['Semantic_Rejections'] = self.semantic_rejections
        payload['Generator_Tokens'] = self.generator_tokens
        payload['Critic_Tokens'] = self.critic_tokens
        payload['Analyst_Tokens'] = self.analyst_tokens
        payload['Total_Tokens'] = self.total_tokens
        payload['Regression_Blindness_Flag'] = int(self.regression_blindness_flag)
        payload['Intent_Target_Agreement'] = self.intent_target_agreement
        payload['Intent_Assertion_Similarity'] = self.intent_assertion_similarity
        payload['Intent_Fixture_Similarity'] = self.intent_fixture_similarity
        payload['Intent_PIT_Component'] = self.intent_pit_component
        payload['Intent_Preservation_Score'] = self.intent_preservation_score
        return payload
