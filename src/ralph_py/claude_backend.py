"""
CLI backend configuration for Claude Code.

This module provides configuration for invoking Claude Code CLI.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import tempfile


class OutputFormat(Enum):
    """Output format supported by Claude CLI."""
    TEXT = "text"  # Plain text output
    STREAM_JSON = "stream-json"  # Newline-delimited JSON stream


class PromptMode(Enum):
    """How to pass prompts to the CLI tool."""
    ARG = "arg"  # Pass prompt as a command-line argument
    STDIN = "stdin"  # Write prompt to stdin


@dataclass
class ClaudeBackend:
    """
    CLI backend configuration for executing Claude Code.
    
    This class provides configuration for how to invoke Claude Code CLI,
    supporting both headless (-p flag) and interactive modes.
    """
    command: str = "claude"
    args: list[str] = field(default_factory=list)
    prompt_mode: PromptMode = PromptMode.ARG
    prompt_flag: Optional[str] = None
    output_format: OutputFormat = OutputFormat.TEXT
    
    @classmethod
    def default(cls) -> "ClaudeBackend":
        """
        Creates the default Claude backend for headless mode.
        
        Uses `-p` flag for headless/print mode execution. This runs Claude
        in non-interactive mode where it executes the prompt and exits.
        
        Emits `--output-format stream-json` for NDJSON streaming output.
        Note: `--verbose` is required when using `--output-format stream-json` with `-p`.
        """
        return cls(
            command="claude",
            args=[
                "--dangerously-skip-permissions",
                "--verbose",
                "--output-format",
                "stream-json",
            ],
            prompt_mode=PromptMode.ARG,
            prompt_flag="-p",
            output_format=OutputFormat.STREAM_JSON,
        )
    
    @classmethod
    def interactive(cls) -> "ClaudeBackend":
        """
        Creates the Claude backend for interactive mode.
        
        Runs Claude without `-p` flag, passing prompt as a positional argument.
        This allows for interactive TUI mode.
        """
        return cls(
            command="claude",
            args=["--dangerously-skip-permissions"],
            prompt_mode=PromptMode.ARG,
            prompt_flag=None,
            output_format=OutputFormat.TEXT,
        )
    
    def build_command(
        self, 
        prompt: str, 
        interactive: bool = False
    ) -> tuple[list[str], Optional[str], Optional[tempfile.NamedTemporaryFile]]:
        """
        Builds the full command with arguments for execution.
        
        Args:
            prompt: The prompt text to pass to Claude
            interactive: Whether to run in interactive mode
            
        Returns:
            Tuple of (command_args, stdin_input, temp_file)
            - command_args: Full command line as a list
            - stdin_input: Input to write to stdin (if prompt_mode is STDIN)
            - temp_file: Temporary file object to keep alive (for large prompts)
        """
        args = self.args.copy()
        
        stdin_input: Optional[str] = None
        temp_file: Optional[tempfile.NamedTemporaryFile] = None
        
        if self.prompt_mode == PromptMode.ARG:
            prompt_text = prompt
            
            # Handle large prompts (>7000 chars) by writing to temp file
            if len(prompt) > 7000:
                try:
                    temp_file = tempfile.NamedTemporaryFile(
                        mode='w', 
                        suffix='.txt', 
                        delete=False
                    )
                    temp_file.write(prompt)
                    temp_file.flush()
                    prompt_text = f"Please read and execute the task in {temp_file.name}"
                except Exception:
                    # Fall back to direct prompt if temp file fails
                    prompt_text = prompt
                    temp_file = None
            
            if self.prompt_flag:
                args.append(self.prompt_flag)
            args.append(prompt_text)
        else:
            # STDIN mode
            stdin_input = prompt
        
        return [self.command] + args, stdin_input, temp_file
