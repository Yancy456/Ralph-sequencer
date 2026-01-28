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


@dataclass
class OrchestratorConfig:
    """Configuration for the orchestrator."""
    max_iterations: int = 10  # Maximum loop iterations
    loop_timeout_secs: int = 0  # Total timeout (0 = no limit)
    iteration_timeout_secs: int = 0  # Per-iteration timeout (0 = no limit)
    break_marker: str = "LOOP_BREAK"  # Marker to signal break
    continue_marker: str = "LOOP_CONTINUE"  # Marker to signal continue to next iteration
    working_directory: Optional[str] = None  # Working directory
    prompt_file: str = "PROMPT.md"  # Default prompt file
    reset_session_iter: int = 5  # Reset session every N iterations (0 = never reset)


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
TextCallback = Callable[[str], None]
ToolCallback = Callable[[str, str, dict], None]
SaveOutputCallback = Callable[[int, str], None]  # Callback to save output (iteration, output)
RawLineCallback = Callable[[int, str], None]  # Callback for raw NDJSON lines (iteration, line)


class Orchestrator:
    """
    Main orchestrator for running Claude Code in a loop.
    
    Runs Claude iteratively until:
    - The break marker is found in output
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
    
    async def run(
        self,
        prompt: str,
        on_iteration: Optional[IterationCallback] = None,
        on_text: Optional[TextCallback] = None,
        on_tool_call: Optional[ToolCallback] = None,
        on_save_output: Optional[SaveOutputCallback] = None,
        on_raw_line: Optional[RawLineCallback] = None,
    ) -> LoopResult:
        """
        Run the orchestration loop.
        
        Args:
            prompt: Initial prompt to execute
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
            
            current_prompt = prompt
            
            while iterations < self.config.max_iterations:
                # Check interrupt
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
                
                iterations += 1
                logger.info(f"Starting iteration {iterations}")
                
                # Handle session management
                reset_iter = self.config.reset_session_iter
                should_reset = reset_iter > 0 and iterations > 1 and (iterations - 1) % reset_iter == 0
                
                if iterations == 1 or should_reset:
                    # First iteration or reset: create new session
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
                    if should_reset:
                        logger.info(f"Session reset at iteration {iterations}")
                else:
                    # Continue existing session: switch from --session-id to -r
                    new_args = []
                    skip_next = False
                    session_id = None
                    for arg in self.backend.args:
                        if skip_next:
                            session_id = arg
                            skip_next = False
                            continue
                        if arg == "--session-id":
                            skip_next = True
                            continue
                        new_args.append(arg)
                    if session_id:
                        new_args.extend(["-r", session_id])
                    self.backend.args = new_args
                
                # Create executor for this iteration
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
                        current_prompt,
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
                
                # Check for continue marker (before break check)
                text_to_check = result.extracted_text or result.stripped_output
                if self._check_continue(text_to_check):
                    logger.info(f"Continue marker found after {iterations} iterations, continuing to next iteration")
                    continue  # Skip to next iteration
                
                # Check for break marker
                if self._check_break(text_to_check):
                    logger.info(f"Break marker found after {iterations} iterations")
                    return LoopResult(
                        status=LoopStatus.COMPLETED,
                        iterations=iterations,
                        total_duration_ms=int((time.time() - start_time) * 1000),
                        total_cost_usd=total_cost,
                        outputs=outputs,
                    )
                
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
                
                # Continue with same prompt for next iteration
            
            # Max iterations reached
            return LoopResult(
                status=LoopStatus.MAX_ITERATIONS,
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
    
    def _check_break(self, output: str) -> bool:
        """Check if the output contains the break marker on its own line."""
        for line in output.splitlines():
            if line.strip() == self.config.break_marker:
                return True
        return False
    
    def _check_continue(self, output: str) -> bool:
        """Check if the output contains the continue marker on its own line."""
        for line in output.splitlines():
            if line.strip() == self.config.continue_marker:
                return True
        return False
    
    async def interrupt(self) -> None:
        """Interrupt the current execution."""
        self._interrupted = True
        if self._executor:
            await self._executor.interrupt()


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
