#!/usr/bin/env python3
"""
CLI entry point for ralph-py.

Usage:
    ralph-py run -p "prompt"           # Run with inline prompt
    ralph-py run                       # Run with PROMPT.md
    ralph-py run --file prompt.txt     # Run with custom prompt file
"""

import argparse
import asyncio
import io
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

OUTPUT_DIR = Path(".ralph_debug")

# Global variable to store the current run directory
_current_run_dir: Optional[Path] = None


def format_ndjson(raw_output: str) -> str:
    """Format NDJSON output with pretty-printed JSON."""
    formatted_lines = []
    for line in raw_output.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            formatted_lines.append(json.dumps(obj, indent=2, ensure_ascii=False))
        except json.JSONDecodeError:
            formatted_lines.append(line)
    return "\n\n".join(formatted_lines)


def format_duration(ms: int) -> str:
    """Format duration in milliseconds to HH:MM:SS format."""
    total_seconds = ms // 1000
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.text import Text
import re

from ralph_py.claude_backend import ClaudeBackend
from ralph_py.executor import ClaudeExecutor, ExecutorConfig, ExecutionResult
from ralph_py.orchestrator import Orchestrator, OrchestratorConfig, LoopStatus, load_prompt

console = Console()
_logger = None  # Will be set in setup_logging
_file_logger = None  # File-only logger for log_print


def _strip_rich_markup(text: str) -> str:
    """Strip Rich markup tags from text."""
    # Remove Rich markup like [bold], [cyan], [/bold], etc.
    return re.sub(r'\[/?[^\]]+\]', '', text)


def log_print(*args, **kwargs) -> None:
    """Print to console and also log to file."""
    # Print to console first
    console.print(*args, **kwargs)
    
    # Also log to file (strip Rich markup for plain text logging)
    # Use file_logger to avoid duplicate console output from RichHandler
    if _file_logger:
        # Use a StringIO buffer to capture plain text output
        buffer = io.StringIO()
        temp_console = Console(file=buffer, force_terminal=False, legacy_windows=False)
        temp_console.print(*args, **kwargs)
        plain_text = buffer.getvalue()
        buffer.close()
        
        # Strip ANSI codes and clean up
        plain_text = _strip_rich_markup(plain_text)
        # Remove extra whitespace but preserve line breaks
        lines = [line.strip() for line in plain_text.split('\n') if line.strip()]
        for line in lines:
            if line:
                _file_logger.info(line)


def log_print_exception() -> None:
    """Print exception to console and also log to file."""
    console.print_exception()
    if _logger:
        import traceback
        _logger.exception("Exception occurred")


def _get_tool_detail(name: str, inputs: dict) -> str:
    """Extract relevant detail from tool inputs for display."""
    if name == "Bash" and "command" in inputs:
        return f" {inputs['command']}"
    elif name in ("Read", "Write", "Edit") and "file_path" in inputs:
        return f" {inputs['file_path']}"
    elif name == "Glob" and "pattern" in inputs:
        return f" {inputs['pattern']}"
    elif name == "Grep" and "pattern" in inputs:
        return f" {inputs['pattern']}"
    return ""


def get_run_dir() -> Path:
    """Get or create the current run directory."""
    global _current_run_dir
    if _current_run_dir is None:
        OUTPUT_DIR.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        _current_run_dir = OUTPUT_DIR / timestamp
        _current_run_dir.mkdir(exist_ok=True)
    return _current_run_dir


def get_output_path(iteration: Optional[int] = None) -> Path:
    """Generate output file path in the current run directory."""
    run_dir = get_run_dir()
    if iteration is not None:
        return run_dir / f"iteration_{iteration}.ndjson"
    return run_dir / "output.ndjson"


def get_log_path() -> Path:
    """Generate log file path in the current run directory."""
    run_dir = get_run_dir()
    return run_dir / "run.log"


def setup_logging() -> None:
    """Set up logging with rich handler and file handler."""
    level = logging.INFO
    log_path = get_log_path()
    
    # Create handlers
    handlers = [
        RichHandler(
            console=console, 
            rich_tracebacks=False, 
            show_time=False, 
            show_level=False,
        ),
        logging.FileHandler(log_path, encoding='utf-8'),
    ]
    
    # File handler format with timestamp
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    handlers[1].setFormatter(file_formatter)
    
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=handlers,
    )
    
    global _logger, _file_logger
    _logger = logging.getLogger(__name__)
    
    # Create a file-only logger for log_print to avoid duplicate console output
    _file_logger = logging.getLogger(f"{__name__}.file_only")
    _file_logger.setLevel(level)
    # Remove all handlers to avoid console output
    _file_logger.handlers = []
    # Add only file handler
    file_handler = logging.FileHandler(log_path, encoding='utf-8')
    file_handler.setFormatter(file_formatter)
    _file_logger.addHandler(file_handler)
    _file_logger.propagate = False  # Don't propagate to root logger
    
    # Log file path only to file, not to console to avoid showing file paths
    _file_logger.info(f"Log file: {log_path}")


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    parser = argparse.ArgumentParser(
        prog="ralph-py",
        description="Python orchestrator for Claude Code CLI",
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    # Run command
    run_parser = subparsers.add_parser("run", help="Run Claude with a prompt")
    run_parser.add_argument(
        "-p", "--prompt",
        type=str,
        help="Inline prompt to execute",
    )
    run_parser.add_argument(
        "-f", "--file",
        type=str,
        default="PROMPT.md",
        help="Prompt file to read (default: PROMPT.md)",
    )
    run_parser.add_argument(
        "--max-iterations",
        type=int,
        default=1,
        help="Maximum loop iterations (default: 1)",
    )
    run_parser.add_argument(
        "--timeout",
        type=int,
        default=0,
        help="Per-iteration timeout in seconds (default: 0, no limit)",
    )
    run_parser.add_argument(
        "--break-marker",
        type=str,
        default="LOOP_BREAK",
        help="Marker to signal loop break (default: LOOP_BREAK)",
    )
    run_parser.add_argument(
        "--continue-marker",
        type=str,
        default="LOOP_CONTINUE",
        help="Marker to signal continue to next iteration (default: LOOP_CONTINUE)",
    )
    run_parser.add_argument(
        "-C", "--directory",
        type=str,
        help="Working directory for execution",
    )
    
    # Stream command (single execution with streaming output)
    stream_parser = subparsers.add_parser("stream", help="Run Claude with streaming output")
    stream_parser.add_argument(
        "-p", "--prompt",
        type=str,
        required=True,
        help="Prompt to execute",
    )
    stream_parser.add_argument(
        "--timeout",
        type=int,
        default=0,
        help="Timeout in seconds (default: 300)",
    )
    stream_parser.add_argument(
        "-C", "--directory",
        type=str,
        help="Working directory for execution",
    )
    
    return parser


async def run_single(
    prompt: str,
    backend: ClaudeBackend,
    config: ExecutorConfig,
) -> int:
    """Run a single execution."""
    log_print(Panel(
        Text(prompt[:500] + "..." if len(prompt) > 500 else prompt),
        title="[bold blue]Prompt[/bold blue]",
        border_style="blue",
    ))
    
    executor = ClaudeExecutor(backend, config)
    cli_started = False
    
    def on_text(text: str) -> None:
        nonlocal cli_started
        if not cli_started:
            log_print("[bold magenta]>>> claude CLI start >>>[/bold magenta]")
            cli_started = True
        log_print(f"[cyan]\\[msg][/cyan] {text}")
    
    def on_tool_call(name: str, tool_id: str, inputs: dict) -> None:
        nonlocal cli_started
        if not cli_started:
            log_print("[bold magenta]>>> claude CLI start >>>[/bold magenta]")
            cli_started = True
        detail = _get_tool_detail(name, inputs)
        log_print(f"[yellow]\\[{name}][/yellow]{detail}")
    
    result = await executor.run(
        prompt,
        on_text=on_text,
        on_tool_call=on_tool_call,
    )
    if cli_started:
        log_print("[bold magenta]<<< claude CLI end <<<[/bold magenta]\n")
    
    # Save NDJSON output to file
    if result.output:
        output_path = get_output_path()
        output_path.write_text(format_ndjson(result.output), encoding='utf-8')
        log_print(f"[dim]NDJSON saved to: {output_path}[/dim]")
    
    # Print result summary
    if result.session_result:
        duration_str = format_duration(result.session_result.duration_ms)
        log_print(Panel(
            f"Duration: {duration_str}\n"
            f"Cost: ${result.session_result.total_cost_usd:.4f}\n"
            f"Turns: {result.session_result.num_turns}",
            title="[bold green]Session Complete[/bold green]",
            border_style="green",
        ))
    
    return 0


async def run_loop(
    prompt: str,
    backend: ClaudeBackend,
    config: OrchestratorConfig,
) -> int:
    """Run the orchestration loop."""
    log_print(Panel(
        Text(prompt[:500] + "..." if len(prompt) > 500 else prompt),
        title="[bold blue]Initial Prompt[/bold blue]",
        border_style="blue",
    ))
    
    logger = logging.getLogger(__name__)
    log_print(f"[dim]Max iterations: {config.max_iterations}[/dim]")
    log_print(f"[dim]Break marker: {config.break_marker}[/dim]")
    log_print(f"[dim]Continue marker: {config.continue_marker}[/dim]")
    
    orchestrator = Orchestrator(backend, config)
    cli_started = False
    
    def on_iteration(iteration: int, result: ExecutionResult) -> None:
        nonlocal cli_started
        # End CLI section if started
        if cli_started:
            log_print("[bold magenta]<<< claude CLI end <<<[/bold magenta]")
            cli_started = False
        status = "✓" if result.success else "✗"
        log_print(f"[bold]Iteration {iteration}[/bold] {status}")
        if result.session_result:
            duration_str = format_duration(result.session_result.duration_ms)
            log_print(f"[dim]Cost: ${result.session_result.total_cost_usd:.4f}[/dim]")
            log_print(f"[dim]Duration: {duration_str}[/dim]")
    
    def on_text(text: str) -> None:
        nonlocal cli_started
        if not cli_started:
            log_print("[bold magenta]>>> claude CLI start >>>[/bold magenta]")
            cli_started = True
        log_print(f"[cyan]\\[msg][/cyan] {text}")
    
    def on_tool_call(name: str, tool_id: str, inputs: dict) -> None:
        nonlocal cli_started
        if not cli_started:
            log_print("[bold magenta]>>> claude CLI start >>>[/bold magenta]")
            cli_started = True
        detail = _get_tool_detail(name, inputs)
        log_print(f"[yellow]\\[{name}][/yellow]{detail}")
    
    def on_save_output(iteration: int, output: str) -> None:
        """Save output when LOOP_CONTINUE is detected."""
        output_path = get_output_path(iteration)
        output_path.write_text(format_ndjson(output), encoding='utf-8')
        log_print(f"[dim]NDJSON saved to: {output_path}[/dim]")
    
    loop_result = await orchestrator.run(
        prompt,
        on_iteration=on_iteration,
        on_text=on_text,
        on_tool_call=on_tool_call,
        on_save_output=on_save_output,
    )
    # End CLI section if still open
    if cli_started:
        log_print("[bold magenta]<<< claude CLI end <<<[/bold magenta]\n")
    
    # Save NDJSON output to file
    if loop_result.outputs:
        output_path = get_output_path()
        output_path.write_text(format_ndjson("\n".join(loop_result.outputs)), encoding='utf-8')
        log_print(f"[dim]NDJSON saved to: {output_path}[/dim]")
    
    # Print final summary
    status_emoji = {
        LoopStatus.COMPLETED: "[green]✓ Completed[/green]",
        LoopStatus.MAX_ITERATIONS: "[yellow]⚠ Max iterations reached[/yellow]",
        LoopStatus.TIMEOUT: "[red]⏱ Timeout[/red]",
        LoopStatus.INTERRUPTED: "[yellow]⚡ Interrupted[/yellow]",
        LoopStatus.ERROR: "[red]✗ Error[/red]",
    }.get(loop_result.status, str(loop_result.status))
    
    duration_str = format_duration(loop_result.total_duration_ms)
    log_print(Panel(
        f"Status: {status_emoji}\n"
        f"Iterations: {loop_result.iterations}\n"
        f"Duration: {duration_str}\n"
        f"Total Cost: ${loop_result.total_cost_usd:.4f}",
        title="[bold]Loop Result[/bold]",
        border_style="blue" if loop_result.status == LoopStatus.COMPLETED else "yellow",
    ))
    
    if loop_result.error:
        log_print(f"[red]Error: {loop_result.error}[/red]")
    
    return 0


async def run_stream(
    prompt: str,
    backend: ClaudeBackend,
    config: ExecutorConfig,
) -> int:
    """Run with streaming output."""
    executor = ClaudeExecutor(backend, config)
    
    cli_started = False
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Running Claude...", total=None)
        
        def on_text(text: str) -> None:
            nonlocal cli_started
            progress.stop()
            if not cli_started:
                log_print("[bold magenta]>>> claude CLI start >>>[/bold magenta]")
                cli_started = True
            log_print(f"[cyan]\\[msg][/cyan] {text}")
        
        def on_tool_call(name: str, tool_id: str, inputs: dict) -> None:
            nonlocal cli_started
            if not cli_started:
                log_print("[bold magenta]>>> claude CLI start >>>[/bold magenta]")
                cli_started = True
            detail = _get_tool_detail(name, inputs)
            log_print(f"[yellow]\\[{name}][/yellow]{detail}")
        
        result = await executor.run(
            prompt,
            on_text=on_text,
            on_tool_call=on_tool_call,
        )
    
    if cli_started:
        log_print("[bold magenta]<<< claude CLI end <<<[/bold magenta]\n")
    
    # Save NDJSON output to file
    if result.output:
        output_path = get_output_path()
        output_path.write_text(format_ndjson(result.output), encoding='utf-8')
        log_print(f"[dim]NDJSON saved to: {output_path}[/dim]")
    
    return 0


def main() -> int:
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 0
    
    setup_logging()
    
    try:
        if args.command == "run":
            # Get prompt
            if args.prompt:
                prompt = args.prompt
            else:
                try:
                    prompt = load_prompt(args.file, args.directory)
                except FileNotFoundError as e:
                    log_print(f"[red]Error: {e}[/red]")
                    return 0
            
            # Create backend
            backend = ClaudeBackend.default()
            
            # Loop execution
            config = OrchestratorConfig(
                max_iterations=args.max_iterations,
                iteration_timeout_secs=args.timeout,
                break_marker=args.break_marker,
                continue_marker=args.continue_marker,
                working_directory=args.directory,
            )
            return asyncio.run(run_loop(prompt, backend, config))
        
        elif args.command == "stream":
            backend = ClaudeBackend.default()
            config = ExecutorConfig(
                idle_timeout_secs=args.timeout,
                working_directory=args.directory,
            )
            return asyncio.run(run_stream(args.prompt, backend, config))
        
        else:
            parser.print_help()
            return 0
            
    except KeyboardInterrupt:
        log_print("\n[yellow]Interrupted[/yellow]")
        return 0
    except Exception as e:
        log_print(f"[red]Error: {e}[/red]")
        log_print_exception()
        return 0


if __name__ == "__main__":
    sys.exit(main())
