#!/usr/bin/env python3
"""
CLI entry point for ralph-py.

Usage:
    ralph-py run --config              # Run with ralph.yaml
    ralph-py run --config <path>       # Run with custom config file
"""

import argparse
import asyncio
import io
import json
import logging
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

OUTPUT_DIR = Path(".ralph_debug")

# Global variables to store the current run context
_current_run_dir: Optional[Path] = None
_current_run_id: Optional[str] = None


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
import re

from ralph_py.claude_backend import ClaudeBackend
from ralph_py.executor import ExecutionResult
from ralph_py.orchestrator import Orchestrator, OrchestratorConfig, LoopStatus
from ralph_py.config import RalphConfig

console = Console()
_logger = None  # Will be set in setup_logging
_file_logger = None  # File-only logger for log_print

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
    if _current_run_id:
        return run_dir / f"{_current_run_id}.log"
    return run_dir / "run.log"


def _sanitize_run_id(run_id: str) -> str:
    """Sanitize run id for filesystem usage."""
    safe_id = run_id.strip()
    if os.sep:
        safe_id = safe_id.replace(os.sep, "_")
    if os.altsep:
        safe_id = safe_id.replace(os.altsep, "_")
    return safe_id


def set_run_id(run_id: str) -> None:
    """Initialize the run id."""
    global _current_run_id
    safe_id = _sanitize_run_id(run_id)
    _current_run_id = safe_id


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
    run_parser = subparsers.add_parser("run", help="Run Claude with configuration file")
    run_parser.add_argument(
        "-m", "--max-iterations",
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
        "-C", "--directory",
        type=str,
        help="Working directory for execution",
    )
    run_parser.add_argument(
        "-c", "--config",
        type=str,
        nargs="?",
        const="ralph.yaml",
        help="Use configuration file to execute repeat sequences (default: ralph.yaml if flag provided)",
    )
    
    return parser


async def run_sequences(
    ralph_config: RalphConfig,
    backend: ClaudeBackend,
    config: OrchestratorConfig,
) -> int:
    """Run sequences from configuration."""
    log_print(Panel(
        f"Executing {len(ralph_config.repeat_sequences)} sequence(s) from configuration",
        title="[bold blue]Configuration Execution[/bold blue]",
        border_style="blue",
    ))
    
    logger = logging.getLogger(__name__)
    
    orchestrator = Orchestrator(backend, config)
    cli_started = False
    
    def on_iteration_start(
        iteration: int,
        sequence_info: str,
        step_info: str,
        role: str,
    ) -> None:
        """Display iteration start information in a panel."""
        # Pre-compute NDJSON path (same as used when streaming starts)
        output_path = get_output_path(iteration)
        # Highlight numeric progress parts in step_info with color and prepend label
        highlighted_step_info = re.sub(
            r"(\d+\/\d+|\d+)",
            r"[bold green]\1[/bold green]",
            step_info,
        )
        highlighted_step_info = f"Progress: {highlighted_step_info}"
        lines = []
        if sequence_info:
            lines.append(sequence_info)
        lines.extend([
            highlighted_step_info,
            f"Role: {role}",
            f"Memory: New session created for step {iteration}",
            f"NDJSON streaming to: {output_path}",
        ])
        content = "\n".join(lines)
        log_print(Panel(
            content,
            title=f"[bold green]Iteration {iteration} Start[/bold green]",
            border_style="green",
        ))
    
    def on_iteration(iteration: int, result: ExecutionResult) -> None:
        nonlocal cli_started
        # End CLI section if started
        if cli_started:
            log_print("[bold magenta]<<< claude CLI end <<<[/bold magenta]")
            cli_started = False
        status = "✓" if result.success else "✗"
        lines = [f"[bold]Iteration {iteration}[/bold] {status}"]
        if result.session_result:
            duration_str = format_duration(result.session_result.duration_ms)
            lines.append(f"[dim]Cost: ${result.session_result.total_cost_usd:.4f}[/dim]")
            lines.append(f"[dim]Duration: {duration_str}[/dim]")
        content = "\n".join(lines)
        log_print(Panel(
            content,
            title=f"[bold blue]Iteration {iteration} Result[/bold blue]",
            border_style="blue",
        ))
    
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
    
    # Track open file handles for real-time NDJSON output
    ndjson_files: dict[int, any] = {}
    
    def on_raw_line(iteration: int, line: str) -> None:
        """Write formatted NDJSON line to file in real-time."""
        if iteration not in ndjson_files:
            output_path = get_output_path(iteration)
            ndjson_files[iteration] = open(output_path, 'w', encoding='utf-8')
        # Format JSON for readability
        line = line.strip()
        if line:
            try:
                obj = json.loads(line)
                formatted = json.dumps(obj, indent=2, ensure_ascii=False)
                ndjson_files[iteration].write(formatted + '\n\n')
            except json.JSONDecodeError:
                ndjson_files[iteration].write(line + '\n')
            ndjson_files[iteration].flush()  # Ensure immediate write
    
    def on_save_output(iteration: int, output: str) -> None:
        """Close file handle after iteration."""
        if iteration in ndjson_files:
            ndjson_files[iteration].close()
            del ndjson_files[iteration]
    
    loop_result = await orchestrator.run_sequences(
        ralph_config,
        on_iteration=on_iteration,
        on_text=on_text,
        on_tool_call=on_tool_call,
        on_save_output=on_save_output,
        on_raw_line=on_raw_line,
        on_iteration_start=on_iteration_start,
    )
    
    # Close any remaining file handles
    for f in ndjson_files.values():
        f.close()
    ndjson_files.clear()
    # End CLI section if still open
    if cli_started:
        log_print("[bold magenta]<<< claude CLI end <<<[/bold magenta]\n")
    
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
        title="[bold]Sequence Execution Result[/bold]",
        border_style="blue" if loop_result.status == LoopStatus.COMPLETED else "yellow",
    ))
    
    if loop_result.error:
        log_print(f"[red]Error: {loop_result.error}[/red]")
    
    return 0


def main() -> int:
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 0
    
    run_id = str(uuid.uuid4())
    set_run_id(run_id)

    setup_logging()
    
    try:
        if args.command == "run":
            # Check if using config file
            # If --config is provided without value, use default "ralph.yaml"
            config_file = args.config if args.config else None
            if not config_file:
                log_print("[red]Error: --config is required. Use --config or --config <path>[/red]")
                return 0
            
            # Load configuration
            try:
                config_path = Path(config_file)
                if not config_path.is_absolute():
                    if args.directory:
                        config_path = Path(args.directory) / config_path
                    else:
                        config_path = Path.cwd() / config_path
                ralph_config = RalphConfig.load(config_path)
            except FileNotFoundError as e:
                log_print(f"[red]Error: {e}[/red]")
                return 0
            except Exception as e:
                log_print(f"[red]Error loading configuration: {e}[/red]")
                log_print_exception()
                return 0
            
            if not ralph_config.repeat_sequences:
                log_print("[yellow]Warning: No repeat_sequences found in configuration file[/yellow]")
                return 0
            
            log_print(Panel(
                f"Loaded {len(ralph_config.repeat_sequences)} sequence(s) from configuration",
                title="[bold blue]Configuration Loaded[/bold blue]",
                border_style="blue",
            ))
            
            # Create backend
            backend = ClaudeBackend.default()
            backend.args.extend(["--session-id", run_id])
            
            # Orchestrator config
            orchestrator_config = OrchestratorConfig(
                max_iterations=args.max_iterations,
                iteration_timeout_secs=args.timeout,
                working_directory=args.directory,
            )
            
            # Run sequences
            return asyncio.run(run_sequences(ralph_config, backend, orchestrator_config))
        
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
