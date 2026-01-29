"""
Executor for running Claude Code CLI.

This module provides subprocess execution for running Claude Code CLI
with streaming NDJSON parsing.
"""

import asyncio
import logging
import os
import signal
from dataclasses import dataclass
from enum import Enum
from typing import AsyncIterator, Callable, Optional, Any

from ralph_py.claude_backend import ClaudeBackend, OutputFormat
from ralph_py.exceptions import RalphExitRequested, RalphContinueRequested
from ralph_py.stream_parser import (
    ClaudeStreamParser,
    AssistantEvent,
    ResultEvent,
    TextContent,
    ToolUseContent,
    SessionResult,
    ClaudeStreamEvent,
)

logger = logging.getLogger(__name__)


class TerminationType(Enum):
    """How the process was terminated."""
    NATURAL = "natural"  # Process exited naturally
    IDLE_TIMEOUT = "idle_timeout"  # Terminated due to idle timeout
    USER_INTERRUPT = "user_interrupt"  # Terminated by user (Ctrl+C)


@dataclass
class ExecutionResult:
    """Result of a CLI execution."""
    output: str = ""  # The accumulated output
    stripped_output: str = ""  # ANSI-stripped output
    extracted_text: str = ""  # Extracted text content from NDJSON stream
    success: bool = False  # Whether the process exited successfully
    exit_code: Optional[int] = None  # The exit code if available
    termination: TerminationType = TerminationType.NATURAL
    session_result: Optional[SessionResult] = None  # Final session stats


@dataclass
class ExecutorConfig:
    """Configuration for executor."""
    idle_timeout_secs: int = 300  # 5 minutes default
    working_directory: Optional[str] = None  # Working directory for command


# Type alias for event callbacks
EventCallback = Callable[[ClaudeStreamEvent], None]
TextCallback = Callable[[str], None]
ToolCallback = Callable[[str, str, dict[str, Any]], None]
RawLineCallback = Callable[[str], None]  # Callback for raw NDJSON lines


class ClaudeExecutor:
    """
    Executor for running Claude Code CLI.
    
    Supports subprocess execution with streaming NDJSON parsing.
    """
    
    def __init__(
        self, 
        backend: Optional[ClaudeBackend] = None,
        config: Optional[ExecutorConfig] = None,
    ):
        """
        Initialize the executor.
        
        Args:
            backend: CLI backend configuration (defaults to Claude)
            config: Executor configuration
        """
        self.backend = backend or ClaudeBackend.default()
        self.config = config or ExecutorConfig()
        self._process: Optional[asyncio.subprocess.Process] = None
        self._interrupted = False
    
    async def run(
        self,
        prompt: str,
        on_text: Optional[TextCallback] = None,
        on_tool_call: Optional[ToolCallback] = None,
        on_event: Optional[EventCallback] = None,
        on_raw_line: Optional[RawLineCallback] = None,
    ) -> ExecutionResult:
        """
        Run Claude with the given prompt.
        
        Args:
            prompt: The prompt to execute
            on_text: Callback for text content
            on_tool_call: Callback for tool invocations (name, id, input)
            on_event: Callback for raw stream events
            on_raw_line: Callback for raw NDJSON lines (for real-time output)
            
        Returns:
            ExecutionResult with output and status
        """
        # Build command
        cmd_args, stdin_input, temp_file = self.backend.build_command(prompt)
        
        logger.debug(f"Executing: {' '.join(cmd_args)}")
        
        try:
            # Create subprocess
            self._process = await asyncio.create_subprocess_exec(
                *cmd_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                stdin=asyncio.subprocess.PIPE if stdin_input else None,
                cwd=self.config.working_directory,
                env={**os.environ, "TERM": "xterm-256color"},
            )
            
            # Write stdin if needed
            if stdin_input and self._process.stdin:
                self._process.stdin.write(stdin_input.encode())
                await self._process.stdin.drain()
                self._process.stdin.close()
            
            # Collect output
            output_lines: list[str] = []
            extracted_text: list[str] = []
            session_result: Optional[SessionResult] = None
            
            if self._process.stdout:
                async for line in self._read_lines(self._process.stdout):
                    output_lines.append(line)
                    
                    # Callback for raw line (real-time output)
                    if on_raw_line:
                        on_raw_line(line)
                    
                    # Parse NDJSON if applicable
                    if self.backend.output_format == OutputFormat.STREAM_JSON:
                        event = ClaudeStreamParser.parse_line(line)
                        if event:
                            # Dispatch callbacks
                            if on_event:
                                on_event(event)
                            
                            if isinstance(event, AssistantEvent):
                                for block in event.message.content:
                                    if isinstance(block, TextContent):
                                        extracted_text.append(block.text)
                                        if on_text:
                                            on_text(block.text)
                                    elif isinstance(block, ToolUseContent):
                                        if on_tool_call:
                                            try:
                                                on_tool_call(block.name, block.id, block.input)
                                            except (RalphExitRequested, RalphContinueRequested):
                                                if self._process:
                                                    self._process.terminate()
                                                    await self._process.wait()
                                                raise
                            
                            elif isinstance(event, ResultEvent):
                                session_result = SessionResult(
                                    duration_ms=event.duration_ms,
                                    total_cost_usd=event.total_cost_usd,
                                    num_turns=event.num_turns,
                                    is_error=event.is_error,
                                )
                    else:
                        # Plain text output
                        if on_text:
                            on_text(line)
            
            # Wait for process to complete
            exit_code = await self._process.wait()
            
            # Determine termination type
            termination = TerminationType.NATURAL
            if self._interrupted:
                termination = TerminationType.USER_INTERRUPT
            elif exit_code == 130:  # SIGINT
                termination = TerminationType.USER_INTERRUPT
            
            output = "\n".join(output_lines)
            
            return ExecutionResult(
                output=output,
                stripped_output=_strip_ansi(output),
                extracted_text="\n".join(extracted_text),
                success=exit_code == 0,
                exit_code=exit_code,
                termination=termination,
                session_result=session_result,
            )
            
        except asyncio.CancelledError:
            if self._process:
                self._process.terminate()
                await self._process.wait()
            raise
        
        finally:
            # Cleanup temp file
            if temp_file:
                try:
                    os.unlink(temp_file.name)
                except Exception:
                    pass
            self._process = None
    
    async def _read_lines(
        self, 
        stream: asyncio.StreamReader
    ) -> AsyncIterator[str]:
        """Read lines from stream with timeout handling."""
        buffer = b""
        
        while True:
            try:
                # Use wait_for with timeout if configured
                if self.config.idle_timeout_secs > 0:
                    chunk = await asyncio.wait_for(
                        stream.read(4096),
                        timeout=self.config.idle_timeout_secs
                    )
                else:
                    chunk = await stream.read(4096)
                
                if not chunk:
                    # EOF - yield any remaining buffer
                    if buffer:
                        yield buffer.decode(errors='replace')
                    break
                
                buffer += chunk
                
                # Split on newlines and yield complete lines
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    yield line.decode(errors='replace')
                    
            except asyncio.TimeoutError:
                logger.warning(f"Idle timeout after {self.config.idle_timeout_secs}s")
                if self._process:
                    self._process.terminate()
                break
    
    async def interrupt(self) -> None:
        """Interrupt the running process."""
        self._interrupted = True
        if self._process:
            try:
                self._process.send_signal(signal.SIGINT)
            except ProcessLookupError:
                pass  # Process already exited
    
    async def terminate(self) -> None:
        """Terminate the running process."""
        self._interrupted = True
        if self._process:
            try:
                self._process.terminate()
            except ProcessLookupError:
                pass


def _strip_ansi(text: str) -> str:
    """Strip ANSI escape sequences from text."""
    import re
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)
