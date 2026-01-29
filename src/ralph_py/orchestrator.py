"""
Orchestrator for running Claude Code in a loop.

This module provides the main orchestration loop that runs Claude iteratively
until a completion condition is met.
"""

import asyncio
import logging
import signal
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from ralph_py.claude_backend import ClaudeBackend
from ralph_py.config import RalphConfig, RepeatSequence, SequenceStep
from ralph_py.exceptions import RalphExitRequested, RalphContinueRequested
from ralph_py.executor import ClaudeExecutor, ExecutorConfig, ExecutionResult

logger = logging.getLogger(__name__)

class LoopStatus(Enum):
    """Status of the orchestration loop."""
    RUNNING = "running"
    COMPLETED = "completed"
    MAX_ITERATIONS = "max_iterations"
    TIMEOUT = "timeout"
    INTERRUPTED = "interrupted"
    ERROR = "error"
    RALPH_EXIT_REQUESTED = "RalphExitRequested"
    RALPH_CONTINUE_REQUESTED = "RalphContinueRequested"


@dataclass
class OrchestratorConfig:
    """Configuration for the orchestrator."""
    max_iterations: int = 10  # Maximum loop iterations
    loop_timeout_secs: int = 0  # Total timeout (0 = no limit)
    iteration_timeout_secs: int = 0  # Per-iteration timeout (0 = no limit)
    working_directory: Optional[str] = None  # Working directory
    prompt_file: str = "PROMPT.md"  # Default prompt file
    reset_session_iter: int = 5  # Reset session every N iterations (0 = never reset)
    resume_from_iteration: int = 0  # Number of iterations to skip (0 = no resume)


@dataclass
class LoopResult:
    """Result of the orchestration loop."""
    status: LoopStatus
    iterations: int = 0
    total_duration_ms: int = 0
    total_cost_usd: float = 0.0
    outputs: list[str] = field(default_factory=list)
    error: Optional[str] = None


# Callback types
IterationCallback = Callable[[int, ExecutionResult], None]
# iteration, sequence_info, step_info, role, prompt_preview
IterationStartCallback = Callable[[int, str, str, str, str], None]
TextCallback = Callable[[str], None]
ToolCallback = Callable[[str, str, dict], None]
SaveOutputCallback = Callable[[int, str], None]  # Callback to save output (iteration, output)
RawLineCallback = Callable[[int, str], None]  # Callback for raw NDJSON lines (iteration, line)


class Orchestrator:
    """
    Main orchestrator for running Claude Code in a loop.

    Runs Claude iteratively until:
    - Maximum iterations reached
    - Timeout occurs
    - User interrupts
    """
    
    def __init__(
        self,
        backend: Optional[ClaudeBackend] = None,
        config: Optional[OrchestratorConfig] = None,
    ):
        """
        Initialize the orchestrator.
        
        Args:
            backend: CLI backend configuration
            config: Orchestrator configuration
        """
        self.backend = backend or ClaudeBackend.default()
        self.config = config or OrchestratorConfig()
        self._interrupted = False
        self._executor: Optional[ClaudeExecutor] = None
    
    async def interrupt(self) -> None:
        """Interrupt the current execution."""
        self._interrupted = True
        if self._executor:
            await self._executor.interrupt()
    
    async def run_sequences(
        self,
        config: RalphConfig,
        on_iteration: Optional[IterationCallback] = None,
            on_text: Optional[TextCallback] = None,
            on_tool_call: Optional[ToolCallback] = None,
            on_save_output: Optional[SaveOutputCallback] = None,
            on_raw_line: Optional[RawLineCallback] = None,
            on_iteration_start: Optional[IterationStartCallback] = None,
    ) -> LoopResult:
        """
        Run repeat sequences from configuration.
        
        Args:
            config: RalphConfig with repeat_sequences
            on_iteration: Callback after each iteration
            on_text: Callback for streaming text
            on_tool_call: Callback for tool invocations
            on_save_output: Callback to save output (iteration, output)
            on_raw_line: Callback for raw NDJSON lines (real-time output)
            
        Returns:
            LoopResult with final status and statistics
        """
        import time
        
        start_time = time.time()
        iterations = 0
        total_cost = 0.0
        outputs: list[str] = []
        
        # Set up signal handlers
        loop = asyncio.get_event_loop()
        
        def handle_interrupt():
            logger.info("Interrupt received")
            self._interrupted = True
            if self._executor:
                asyncio.create_task(self._executor.interrupt())
        
        # Install signal handler
        try:
            loop.add_signal_handler(signal.SIGINT, handle_interrupt)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass
        
        try:
            # Create executor
            executor_config = ExecutorConfig(
                idle_timeout_secs=self.config.iteration_timeout_secs,
                working_directory=self.config.working_directory,
            )
            
            # Execute each repeat sequence
            for seq_idx, repeat_seq in enumerate(config.repeat_sequences):
                if self._interrupted:
                    return LoopResult(
                        status=LoopStatus.INTERRUPTED,
                        iterations=iterations,
                        total_duration_ms=int((time.time() - start_time) * 1000),
                        total_cost_usd=total_cost,
                        outputs=outputs,
                    )
                
                # Sequence-level info is now handled by CLI via on_iteration_start
                logger.debug(f"Executing sequence {seq_idx + 1}/{len(config.repeat_sequences)} with {repeat_seq.repeat} repeats")
                
                # Repeat the sequence
                for repeat_num in range(repeat_seq.repeat):
                    if self._interrupted:
                        return LoopResult(
                            status=LoopStatus.INTERRUPTED,
                            iterations=iterations,
                            total_duration_ms=int((time.time() - start_time) * 1000),
                            total_cost_usd=total_cost,
                            outputs=outputs,
                        )
                    
                    # Check total timeout (0 = no limit)
                    elapsed = time.time() - start_time
                    if self.config.loop_timeout_secs > 0 and elapsed > self.config.loop_timeout_secs:
                        return LoopResult(
                            status=LoopStatus.TIMEOUT,
                            iterations=iterations,
                            total_duration_ms=int(elapsed * 1000),
                            total_cost_usd=total_cost,
                            outputs=outputs,
                        )
                    
                    # Execute each step in the sequence
                    for step_idx, step in enumerate(repeat_seq.steps):
                        if self._interrupted:
                            return LoopResult(
                                status=LoopStatus.INTERRUPTED,
                                iterations=iterations,
                                total_duration_ms=int((time.time() - start_time) * 1000),
                                total_cost_usd=total_cost,
                                outputs=outputs,
                            )
                        
                        next_iteration = iterations + 1
                        # Skip iterations if resuming from a previous run
                        if self.config.resume_from_iteration and next_iteration <= self.config.resume_from_iteration:
                            iterations = next_iteration
                            logger.debug(
                                "Skipping iteration %d during resume (step %d/%d, sequence %d/%d, repeat %d/%d)",
                                iterations,
                                step_idx + 1,
                                len(repeat_seq.steps),
                                seq_idx + 1,
                                len(config.repeat_sequences),
                                repeat_num + 1,
                                repeat_seq.repeat,
                            )
                            continue
                        
                        iterations = next_iteration
                        # Step-level info is now handled by CLI via on_iteration_start
                        logger.debug(
                            "Executing iteration %d (step %d/%d, sequence %d/%d, repeat %d/%d)",
                            iterations,
                            step_idx + 1,
                            len(repeat_seq.steps),
                            seq_idx + 1,
                            len(config.repeat_sequences),
                            repeat_num + 1,
                            repeat_seq.repeat,
                        )
                        
                        # Get prompt for this step
                        prompt = step.prompt
                        if not prompt or (isinstance(prompt, str) and not prompt.strip()):
                            # Try to load from role's prompt_file
                            prompt = config.get_role_prompt(step.role, self.config.working_directory)
                            if not prompt:
                                logger.warning(f"No prompt found for role '{step.role}', skipping step")
                                continue

                        # Build a single-line prompt preview (long text truncated with ellipsis)
                        prompt_preview = ""
                        if isinstance(prompt, str):
                            single_line = " ".join(prompt.splitlines()).strip()
                            max_len = 120
                            if len(single_line) > max_len:
                                prompt_preview = single_line[: max_len - 1] + "…"
                            else:
                                prompt_preview = single_line
                        
                        # Notify iteration start with detailed info (step + role + prompt preview)
                        if on_iteration_start:
                            sequence_info = ""
                            step_info = (
                                f"Step {step_idx + 1}/{len(repeat_seq.steps)} of sequence "
                                f"{seq_idx + 1}/{len(config.repeat_sequences)}, "
                                f"repeat {repeat_num + 1}/{repeat_seq.repeat}"
                            )
                            role_name = step.role
                            on_iteration_start(
                                iterations,
                                sequence_info,
                                step_info,
                                role_name,
                                prompt_preview,
                            )
                        
                        # Always create a new session for each step
                        new_session_id = str(uuid.uuid4())
                        new_args = []
                        skip_next = False
                        for arg in self.backend.args:
                            if skip_next:
                                skip_next = False
                                continue
                            if arg in ("--session-id", "-r"):
                                skip_next = True
                                continue
                            new_args.append(arg)
                        new_args.extend(["--session-id", new_session_id])
                        self.backend.args = new_args
                        # Session creation info is now surfaced by CLI
                        logger.debug(f"New session created for step {iterations}")
                        
                        # Create executor for this step
                        self._executor = ClaudeExecutor(self.backend, executor_config)
                        
                        # Run Claude
                        try:
                            # Wrap on_raw_line to include iteration number
                            def make_raw_line_callback(iter_num: int):
                                def callback(line: str):
                                    if on_raw_line:
                                        on_raw_line(iter_num, line)
                                return callback
                            
                            result = await self._executor.run(
                                prompt,
                                on_text=on_text,
                                on_tool_call=on_tool_call,
                                on_raw_line=make_raw_line_callback(iterations),
                            )
                        except asyncio.CancelledError:
                            return LoopResult(
                                status=LoopStatus.INTERRUPTED,
                                iterations=iterations,
                                total_duration_ms=int((time.time() - start_time) * 1000),
                                total_cost_usd=total_cost,
                                outputs=outputs,
                            )
                        except RalphExitRequested:
                            return LoopResult(
                                status=LoopStatus.RALPH_EXIT_REQUESTED,
                                iterations=iterations,
                                total_duration_ms=int((time.time() - start_time) * 1000),
                                total_cost_usd=total_cost,
                                outputs=outputs,
                            )
                        except RalphContinueRequested:
                            # Skip current step, continue to next step in the loop
                            continue
                        
                        # Collect output
                        outputs.append(result.output)
                        
                        # Update cost
                        if result.session_result:
                            total_cost += result.session_result.total_cost_usd
                        
                        # Callback
                        if on_iteration:
                            on_iteration(iterations, result)
                        
                        # Save output for each iteration
                        if on_save_output and result.output:
                            on_save_output(iterations, result.output)
                        
                        # Check for errors
                        if not result.success and result.exit_code not in (0, 130):
                            return LoopResult(
                                status=LoopStatus.ERROR,
                                iterations=iterations,
                                total_duration_ms=int((time.time() - start_time) * 1000),
                                total_cost_usd=total_cost,
                                outputs=outputs,
                                error=f"Process exited with code {result.exit_code}",
                            )
            
            # All sequences completed
            return LoopResult(
                status=LoopStatus.COMPLETED,
                iterations=iterations,
                total_duration_ms=int((time.time() - start_time) * 1000),
                total_cost_usd=total_cost,
                outputs=outputs,
            )
        
        finally:
            # Remove signal handler
            try:
                loop.remove_signal_handler(signal.SIGINT)
            except (NotImplementedError, ValueError):
                pass
            self._executor = None


def load_prompt(
    prompt_file: str = "PROMPT.md",
    working_directory: Optional[str] = None,
) -> str:
    """
    Load prompt from a file.
    
    Args:
        prompt_file: Path to prompt file (relative to working_directory)
        working_directory: Base directory (defaults to current directory)
        
    Returns:
        Prompt content as string
        
    Raises:
        FileNotFoundError: If prompt file doesn't exist
    """
    if working_directory:
        path = Path(working_directory) / prompt_file
    else:
        path = Path(prompt_file)
    
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    
    return path.read_text(encoding='utf-8')
