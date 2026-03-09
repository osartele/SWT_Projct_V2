from __future__ import annotations

import json
import math
import os
import re
import shlex
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import gradleLib
import mavenLib
import utils
from agentic_build import (
    apply_evolution_spec,
    create_sample_workspace,
    file_sha256,
    instrument_workspace,
    restore_instrumentation,
    run_build_with_metrics,
    run_human_baseline,
    run_human_stale_check,
    write_candidate_code,
)
from agentic_types import AgentTurn, BenchmarkSample, BuildExecutionResult, EvolutionSpec, MappingResult, SyncResult


def _is_windows() -> bool:
    return os.name == 'nt'


class GeminiCliInvoker:
    def invoke(self, role: str, prompt: str, workdir: Path, command: str) -> Tuple[str, float]:
        start = time.perf_counter()
        parts = shlex.split(command, posix=not _is_windows())
        if not parts:
            raise RuntimeError('gemini_cli_command_missing')
        if not workdir.exists():
            raise RuntimeError('gemini_cli_workdir_missing:%s' % workdir)
        try:
            if _is_windows():
                result = self._run_command_via_powershell(parts, prompt, workdir)
            else:
                result = self._run_command(parts, prompt, workdir)
        except FileNotFoundError as error:
            raise RuntimeError('gemini_cli_command_not_found:%s' % parts[0]) from error
        duration = time.perf_counter() - start
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or 'gemini_cli_failed')
        return result.stdout.strip(), duration

    def _run_command(self, parts: List[str], prompt: str, workdir: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(parts + ['-p', prompt], cwd=str(workdir), capture_output=True, text=True, timeout=300)

    def _run_command_via_powershell(self, parts: List[str], prompt: str, workdir: Path) -> subprocess.CompletedProcess[str]:
        powershell = shutil.which('powershell.exe') or shutil.which('pwsh.exe')
        if not powershell:
            raise RuntimeError('gemini_cli_command_not_found:%s' % parts[0])
        script = (
            "$ErrorActionPreference = 'Stop'; "
            "$commandParts = ConvertFrom-Json $env:AGONE_AGENT_COMMAND_JSON; "
            "if ($null -eq $commandParts -or $commandParts.Count -lt 1) { throw 'gemini_cli_command_missing' }; "
            "$cmd = $commandParts[0]; "
            "$cmdArgs = @(); "
            "if ($commandParts.Count -gt 1) { $cmdArgs = @($commandParts[1..($commandParts.Count - 1)]) }; "
            "$env:AGONE_AGENT_PROMPT | & $cmd @cmdArgs -p ' '"
        )
        env = os.environ.copy()
        env['AGONE_AGENT_COMMAND_JSON'] = json.dumps(parts)
        env['AGONE_AGENT_PROMPT'] = prompt
        return subprocess.run(
            [powershell, '-NoLogo', '-NonInteractive', '-Command', script],
            cwd=str(workdir),
            capture_output=True,
            text=True,
            timeout=300,
            env=env,
        )


class MockGeminiCliInvoker(GeminiCliInvoker):
    def __init__(self, responses: Optional[Dict[str, List[str]]] = None) -> None:
        self.responses = responses or {}

    def invoke(self, role: str, prompt: str, workdir: Path, command: str) -> Tuple[str, float]:
        queue = self.responses.get(role, [])
        if not queue:
            if role == 'critic':
                return ('{"verdict":"approve","regression_blindness_flags":[],"required_changes":[]}', 0.0)
            if role == 'analyst':
                return ('{"root_cause":"mock","failure_class":"mock","repair_actions":["mock"]}', 0.0)
            return ('public class PlaceholderTest {}', 0.0)
        return queue.pop(0), 0.0


def approximate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, math.ceil(len(re.findall(r'\w+|[^\w\s]', text, re.UNICODE)) * 0.75))


def extract_code_block(text: str) -> str:
    fenced = re.search(r'```(?:java)?\s*(.*?)```', text, re.DOTALL)
    if fenced:
        return fenced.group(1).strip()
    return text.strip()


def parse_json_response(text: str) -> Dict[str, Any]:
    cleaned = text.strip()
    fenced = re.search(r'```(?:json)?\s*(.*?)```', cleaned, re.DOTALL)
    if fenced:
        cleaned = fenced.group(1).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return {'verdict': 'reject', 'regression_blindness_flags': ['invalid_json'], 'required_changes': [cleaned]}


def extract_assertions(code: str) -> List[str]:
    assertions = []
    for line in code.splitlines():
        stripped = line.strip()
        if 'assert' in stripped.lower():
            assertions.append(re.sub(r'\s+', ' ', stripped))
    return assertions


def extract_test_method_body(code: str, test_method_name: str) -> str:
    pattern = re.compile(r'([^{;]*\b%s\s*\([^)]*\)\s*\{)' % re.escape(test_method_name))
    match = pattern.search(code)
    if match is None:
        return ''
    body_start = code.find('{', match.end(1) - 1)
    depth = 0
    end = None
    for index in range(body_start, len(code)):
        char = code[index]
        if char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                end = index + 1
                break
    if end is None:
        return ''
    return code[body_start:end]


def jaccard_similarity(left: List[str], right: List[str]) -> float:
    left_set = set(left)
    right_set = set(right)
    if not left_set and not right_set:
        return 1.0
    if not left_set or not right_set:
        return 0.0
    return round(len(left_set & right_set) / float(len(left_set | right_set)), 4)


def deterministic_regression_guard(original_code: str, candidate_code: str, mapped_method: str, test_method_name: str) -> List[str]:
    flags: List[str] = []
    original_assertions = extract_assertions(original_code)
    candidate_assertions = extract_assertions(candidate_code)
    if not candidate_assertions:
        flags.append('empty_or_missing_assertions')
    if original_assertions and len(candidate_assertions) < len(original_assertions):
        flags.append('assertions_removed')
    if mapped_method and mapped_method not in candidate_code:
        flags.append('mapped_focal_method_not_exercised')
    lowered = candidate_code.lower()
    for marker in ('@disabled', '@ignore', 'assume.', 'assumptions.'):
        if marker in lowered:
            flags.append('test_disabled_or_softened')
            break
    test_body = extract_test_method_body(candidate_code, test_method_name)
    if test_body and re.search(r'catch\s*\(\s*(?:Exception|Throwable)\s+\w+\s*\)\s*\{\s*\}', test_body):
        flags.append('broad_exception_swallowing')
    return sorted(set(flags))


def _build_blackboard(sample: BenchmarkSample, mapping: MappingResult, evolution: EvolutionSpec, strategy: str, original_test_code: str, baseline_result: BuildExecutionResult, stale_result: BuildExecutionResult) -> Dict[str, Any]:
    return {
        'sample': sample.to_dict(),
        'mapping': mapping.to_dict(),
        'evolution': evolution.to_dict(),
        'strategy': strategy,
        'original_human_test': original_test_code,
        'baseline_human_result': baseline_result.to_dict(),
        'stale_human_result': stale_result.to_dict(),
        'execution_iteration_count': 0,
        'inter_agent_loop_count': 0,
        'critic_rejections': [],
        'analyst_summaries': [],
        'latest_candidate_test_path': None,
        'latest_candidate_hash': None,
        'latest_build_status': None,
        'latest_log_paths': {},
    }


def _write_blackboard(path: Path, blackboard: Dict[str, Any]) -> None:
    path.write_text(json.dumps(blackboard, indent=2), encoding='utf-8')


def _record_turn(turns: List[AgentTurn], sample_id: str, strategy: str, execution_iteration: int, semantic_iteration: int, role: str, message_type: str, prompt: str, response: str, elapsed: float, verdict: Optional[str] = None, notes: Optional[str] = None) -> None:
    turns.append(
        AgentTurn(
            sample_id=sample_id,
            strategy=strategy,
            execution_iteration=execution_iteration,
            semantic_iteration=semantic_iteration,
            agent_role=role,
            message_type=message_type,
            prompt_text=prompt,
            response_text=response,
            prompt_tokens=approximate_tokens(prompt),
            completion_tokens=approximate_tokens(response),
            wall_clock_seconds=round(elapsed, 4),
            verdict=verdict,
            notes=notes,
        )
    )


def _generator_prompt(blackboard: Dict[str, Any], strategy: str) -> str:
    return (
        'You are the Generator, a JUnit test engineer.\n'
        'You must output only the full Java test class, with no prose.\n'
        'Use the shared blackboard JSON below as the source of truth.\n'
        'If the strategy is iterative_healing, minimally patch the existing test while preserving unaffected code.\n'
        'If the strategy is regenerative, rewrite the full test class to fit the evolved source.\n'
        'Do not remove assertions unless you replace them with stronger checks tied to the mapped focal method.\n\n'
        'STRATEGY: %s\n\nBLACKBOARD:\n%s' % (strategy, json.dumps(blackboard, indent=2))
    )


def _critic_prompt(blackboard: Dict[str, Any], candidate_code: str) -> str:
    return (
        'You are the Critic, a semantic reviewer for autonomous test synchronization.\n'
        'Review the candidate test and compare it to the original human test in the blackboard.\n'
        'Reject the candidate if assertions were removed rather than updated, if the mapped focal method is no longer exercised, '
        'if the test is disabled, empty, or softened, or if fixture setup erased the original intent.\n'
        'Respond with strict JSON using keys: verdict, regression_blindness_flags, required_changes, rationale.\n\n'
        'BLACKBOARD:\n%s\n\nCANDIDATE TEST:\n%s' % (json.dumps(blackboard, indent=2), candidate_code)
    )


def _analyst_prompt(blackboard: Dict[str, Any], logs: str, candidate_code: str) -> str:
    return (
        'You are the Analyst, an execution decoder for test synchronization failures.\n'
        'Read the raw compiler or JUnit output and explain the likely root cause in plain English.\n'
        'Respond with strict JSON using keys: root_cause, failure_class, repair_actions.\n\n'
        'BLACKBOARD:\n%s\n\nFAILURE LOGS:\n%s\n\nCANDIDATE TEST:\n%s'
        % (json.dumps(blackboard, indent=2), logs, candidate_code)
    )


def _intent_metrics(original_code: str, candidate_code: str, mapped_method: Optional[str], mutation_coverage: Optional[float], baseline_mutation: Optional[float]) -> Dict[str, float]:
    original_assertions = extract_assertions(original_code)
    candidate_assertions = extract_assertions(candidate_code)
    original_fixture = [line.strip() for line in original_code.splitlines() if 'assert' not in line.lower() and line.strip()]
    candidate_fixture = [line.strip() for line in candidate_code.splitlines() if 'assert' not in line.lower() and line.strip()]
    target_agreement = 1.0 if mapped_method and mapped_method in candidate_code else 0.0
    assertion_similarity = jaccard_similarity(original_assertions, candidate_assertions)
    fixture_similarity = jaccard_similarity(original_fixture, candidate_fixture)
    if mutation_coverage is None:
        pit_component = 0.0
    elif baseline_mutation is None or baseline_mutation == 0:
        pit_component = min(mutation_coverage / 100.0, 1.0)
    else:
        pit_component = max(0.0, min(mutation_coverage / baseline_mutation, 1.0))
    preservation = round((target_agreement + assertion_similarity + fixture_similarity + pit_component) / 4.0, 4)
    return {
        'Intent_Target_Agreement': target_agreement,
        'Intent_Assertion_Similarity': assertion_similarity,
        'Intent_Fixture_Similarity': fixture_similarity,
        'Intent_PIT_Component': pit_component,
        'Intent_Preservation_Score': preservation,
    }


def _sum_role_tokens(turns: List[AgentTurn], role: str) -> int:
    return sum(turn.prompt_tokens + turn.completion_tokens for turn in turns if turn.agent_role == role)


def _run_evosuite_baseline(sample: BenchmarkSample, sample_root: Path) -> BuildExecutionResult:
    evolved_root = sample_root / 'evolved_repo'
    build_metadata = sample.build_metadata
    if build_metadata is None:
        return BuildExecutionResult(False, '', '', 'missing_build_metadata', 0, None, None, None, None)
    module_root = Path(build_metadata.module_path)
    relative_module = module_root.relative_to(sample.repo_path)
    workspace_module = evolved_root / relative_module
    system_name = 'Windows' if os.name == 'nt' else 'Linux'
    if build_metadata.build_system == 'maven':
        original_pom = mavenLib.add_evosuite_pom(str(workspace_module))
        try:
            if not mavenLib.run_evosuite_generation_maven(str(workspace_module), sample.focal_class_path, system_name):
                return BuildExecutionResult(False, '', '', 'evosuite_generation_failed', 0, None, None, None, None)
            target_path = evolved_root / sample.test_class_path
            evosuite_path = Path(str(target_path).replace('%s.java' % sample.test_class_name, '%s_ESTest.java' % sample.focal_class_name))
            if not evosuite_path.exists():
                return BuildExecutionResult(False, '', '', 'evosuite_output_missing', 0, None, None, None, None)
            content = evosuite_path.read_text(encoding='utf-8').replace('public class %s_ESTest' % sample.focal_class_name, 'public class %s' % sample.test_class_name)
            target_path.write_text(content, encoding='utf-8')
            original_instrumented, module_path = instrument_workspace(sample, evolved_root)
            try:
                return run_build_with_metrics(sample, module_path or str(workspace_module), evolved_root)
            finally:
                restore_instrumentation(sample, module_path, original_instrumented)
        finally:
            if original_pom is not None:
                original_pom.write(os.path.join(str(workspace_module), 'pom.xml'))
            utils.remove_evosuite_scaffolding_files([str(evolved_root / sample.test_class_path)])
    original_build = gradleLib.add_evosuite_build_gradle(str(workspace_module))
    try:
        instrumented, module_path = instrument_workspace(sample, evolved_root)
        try:
            subprocess.run(['gradle.bat' if os.name == 'nt' else 'gradle', 'clean', 'classes'], cwd=str(workspace_module), capture_output=True, text=True, timeout=900)
            if not gradleLib.run_evosuite_generation_gradle(str(evolved_root / sample.focal_class_path)):
                return BuildExecutionResult(False, '', '', 'evosuite_generation_failed', 0, None, None, None, None)
            evosuite_path = Path('evosuite-tests') / Path(sample.test_class_path.replace('%s.java' % sample.test_class_name, '%s_ESTest.java' % sample.focal_class_name))
            if not evosuite_path.exists():
                return BuildExecutionResult(False, '', '', 'evosuite_output_missing', 0, None, None, None, None)
            target_path = evolved_root / sample.test_class_path
            content = evosuite_path.read_text(encoding='utf-8').replace('public class %s_ESTest' % sample.focal_class_name, 'public class %s' % sample.test_class_name)
            target_path.write_text(content, encoding='utf-8')
            return run_build_with_metrics(sample, module_path or str(workspace_module), evolved_root)
        finally:
            restore_instrumentation(sample, module_path, instrumented)
    finally:
        if original_build is not None:
            gradleLib.write_build_gradle(str(workspace_module), original_build)
        utils.remove_directory_evosuite_command_line()


class GeminiCliSocietyRunner:
    def __init__(self, config: Dict[str, Any], invoker: Optional[GeminiCliInvoker] = None) -> None:
        self.config = config
        self.invoker = invoker or GeminiCliInvoker()

    def run_sample(self, sample: BenchmarkSample, mapping: MappingResult, evolution: EvolutionSpec, strategy: str) -> Tuple[SyncResult, List[AgentTurn], Dict[str, BuildExecutionResult]]:
        workspace_root = Path(self.config['paths']['workspace_dir'])
        sample_root = create_sample_workspace(sample, workspace_root, strategy)
        original_test_path = sample_root / 'baseline_repo' / sample.test_class_path
        original_test_code = original_test_path.read_text(encoding='utf-8')
        baseline_result = run_human_baseline(sample, sample_root) if self.config['baselines']['run_human'] else BuildExecutionResult(False, '', '', 'skipped', 0, None, None, None, None)
        stale_result = run_human_stale_check(sample, sample_root, evolution)

        blackboard = _build_blackboard(sample, mapping, evolution, strategy, original_test_code, baseline_result, stale_result)
        blackboard_path = sample_root / 'blackboard.json'
        _write_blackboard(blackboard_path, blackboard)
        turns: List[AgentTurn] = []
        extra_results: Dict[str, BuildExecutionResult] = {}

        evolved_root = sample_root / 'evolved_repo'
        if not apply_evolution_spec(evolution, evolved_root):
            result = SyncResult(
                sample_id=sample.sample_id,
                project_id=sample.project_id,
                generator='gemini-cli',
                prompt_technique=strategy,
                mapped_focal_method=mapping.ast_prediction,
                mapping_correct=mapping.ast_correct,
                evolution_operator=evolution.operator,
                converged=False,
                compilation=0,
                branch_coverage=None,
                line_coverage=None,
                method_coverage=None,
                mutation_coverage=None,
                inter_agent_loops=0,
                execution_iterations=0,
                semantic_rejections=0,
                generator_tokens=0,
                critic_tokens=0,
                analyst_tokens=0,
                total_tokens=0,
                regression_blindness_flag=True,
                intent_target_agreement=0.0,
                intent_assertion_similarity=0.0,
                intent_fixture_similarity=0.0,
                intent_pit_component=0.0,
                intent_preservation_score=0.0,
                convergence_path='evolution_apply_failed',
                blackboard_path=str(blackboard_path),
                transcript_path=None,
                error_message='failed_to_apply_evolution_spec',
            )
            return result, turns, extra_results

        original_instrumentation, module_path = instrument_workspace(sample, evolved_root)
        try:
            max_rejections = int(self.config['limits']['max_semantic_rejections'])
            max_iterations = int(self.config['limits']['max_execution_iterations'])
            semantic_rejections = 0
            inter_agent_loops = 0
            candidate_code = original_test_code
            build_result = BuildExecutionResult(False, '', '', 'not_run', 0, None, None, None, None)
            converged = False
            convergence_path = 'max_iterations_reached'

            for execution_iteration in range(1, max_iterations + 1):
                while True:
                    semantic_iteration = semantic_rejections + 1
                    prompt = _generator_prompt(blackboard, strategy)
                    response, elapsed = self.invoker.invoke('generator', prompt, sample_root, self.config['agents']['generator']['command'])
                    candidate_code = extract_code_block(response)
                    _record_turn(turns, sample.sample_id, strategy, execution_iteration, semantic_iteration, 'Generator', 'Code Proposal', prompt, response, elapsed)
                    candidate_path = write_candidate_code(evolved_root, sample, candidate_code)
                    blackboard['latest_candidate_test_path'] = str(candidate_path)
                    blackboard['latest_candidate_hash'] = file_sha256(candidate_path)

                    critic_prompt = _critic_prompt(blackboard, candidate_code)
                    critic_response, critic_elapsed = self.invoker.invoke('critic', critic_prompt, sample_root, self.config['agents']['critic']['command'])
                    verdict = parse_json_response(critic_response)
                    deterministic_flags = deterministic_regression_guard(original_test_code, candidate_code, mapping.ast_prediction or sample.labeled_focal_method, sample.test_method_name)
                    if deterministic_flags:
                        verdict['verdict'] = 'reject'
                        verdict.setdefault('regression_blindness_flags', [])
                        verdict['regression_blindness_flags'] = sorted(set(verdict['regression_blindness_flags']) | set(deterministic_flags))
                    _record_turn(turns, sample.sample_id, strategy, execution_iteration, semantic_iteration, 'Critic', 'Review Critique', critic_prompt, critic_response, critic_elapsed, verdict=verdict.get('verdict'), notes=';'.join(verdict.get('regression_blindness_flags', [])))
                    if verdict.get('verdict') == 'approve':
                        break
                    semantic_rejections += 1
                    inter_agent_loops += 1
                    blackboard['inter_agent_loop_count'] = inter_agent_loops
                    blackboard['critic_rejections'].append(verdict)
                    _write_blackboard(blackboard_path, blackboard)
                    if semantic_rejections >= max_rejections:
                        convergence_path = 'semantic_non_convergence'
                        break

                if semantic_rejections >= max_rejections:
                    break

                build_result = run_build_with_metrics(sample, module_path or str(evolved_root), evolved_root)
                log_dir = sample_root / 'logs'
                log_dir.mkdir(exist_ok=True)
                stdout_path = log_dir / ('execution_%s_stdout.log' % execution_iteration)
                stderr_path = log_dir / ('execution_%s_stderr.log' % execution_iteration)
                stdout_path.write_text(build_result.stdout, encoding='utf-8')
                stderr_path.write_text(build_result.stderr, encoding='utf-8')
                blackboard['execution_iteration_count'] = execution_iteration
                blackboard['latest_build_status'] = build_result.to_dict()
                blackboard['latest_log_paths'] = {'stdout': str(stdout_path), 'stderr': str(stderr_path)}
                _write_blackboard(blackboard_path, blackboard)

                if build_result.success:
                    post_flags = deterministic_regression_guard(original_test_code, candidate_code, mapping.ast_prediction or sample.labeled_focal_method, sample.test_method_name)
                    if post_flags:
                        semantic_rejections += 1
                        inter_agent_loops += 1
                        blackboard['critic_rejections'].append({'verdict': 'reject', 'regression_blindness_flags': post_flags, 'required_changes': post_flags})
                        _write_blackboard(blackboard_path, blackboard)
                        if semantic_rejections >= max_rejections:
                            convergence_path = 'semantic_non_convergence'
                            break
                        continue
                    converged = True
                    convergence_path = 'critic_approved_execution_pass'
                    break

                logs = '\n'.join([
                    build_result.summary,
                    build_result.stdout[: int(self.config['limits']['max_failure_log_chars'])],
                    build_result.stderr[: int(self.config['limits']['max_failure_log_chars'])],
                ])
                analyst_prompt = _analyst_prompt(blackboard, logs, candidate_code)
                analyst_response, analyst_elapsed = self.invoker.invoke('analyst', analyst_prompt, sample_root, self.config['agents']['analyst']['command'])
                analysis = parse_json_response(analyst_response)
                blackboard['analyst_summaries'].append(analysis)
                _write_blackboard(blackboard_path, blackboard)
                _record_turn(turns, sample.sample_id, strategy, execution_iteration, semantic_rejections + 1, 'Analyst', 'Execution Summary', analyst_prompt, analyst_response, analyst_elapsed, verdict='fail', notes=analysis.get('root_cause'))

            transcript_path = sample_root / 'agent_turns.json'
            transcript_path.write_text(json.dumps([turn.to_dict() for turn in turns], indent=2), encoding='utf-8')
            generator_tokens = _sum_role_tokens(turns, 'Generator')
            critic_tokens = _sum_role_tokens(turns, 'Critic')
            analyst_tokens = _sum_role_tokens(turns, 'Analyst')
            intent = _intent_metrics(original_test_code, candidate_code, mapping.ast_prediction or sample.labeled_focal_method, build_result.mutation_coverage, baseline_result.mutation_coverage)
            sync_result = SyncResult(
                sample_id=sample.sample_id,
                project_id=sample.project_id,
                generator='gemini-cli',
                prompt_technique=strategy,
                mapped_focal_method=mapping.ast_prediction,
                mapping_correct=mapping.ast_correct,
                evolution_operator=evolution.operator,
                converged=converged,
                compilation=build_result.compilation,
                branch_coverage=build_result.branch_coverage,
                line_coverage=build_result.line_coverage,
                method_coverage=build_result.method_coverage,
                mutation_coverage=build_result.mutation_coverage,
                inter_agent_loops=inter_agent_loops,
                execution_iterations=blackboard['execution_iteration_count'],
                semantic_rejections=semantic_rejections,
                generator_tokens=generator_tokens,
                critic_tokens=critic_tokens,
                analyst_tokens=analyst_tokens,
                total_tokens=generator_tokens + critic_tokens + analyst_tokens,
                regression_blindness_flag=not converged,
                intent_target_agreement=intent['Intent_Target_Agreement'],
                intent_assertion_similarity=intent['Intent_Assertion_Similarity'],
                intent_fixture_similarity=intent['Intent_Fixture_Similarity'],
                intent_pit_component=intent['Intent_PIT_Component'],
                intent_preservation_score=intent['Intent_Preservation_Score'],
                convergence_path=convergence_path,
                blackboard_path=str(blackboard_path),
                transcript_path=str(transcript_path),
                error_message=None if converged else build_result.summary,
            )
            if self.config['baselines']['run_evosuite']:
                extra_results['evosuite'] = _run_evosuite_baseline(sample, sample_root)
            if self.config['baselines']['run_human']:
                extra_results['human'] = stale_result
                extra_results['human_reference'] = baseline_result
            return sync_result, turns, extra_results
        finally:
            restore_instrumentation(sample, module_path, original_instrumentation)





