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
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

OUTPUT_DIR = Path(".ralph_debug")


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

from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.text import Text

from ralph_py.claude_backend import ClaudeBackend
from ralph_py.executor import ClaudeExecutor, ExecutorConfig, ExecutionResult
from ralph_py.orchestrator import Orchestrator, OrchestratorConfig, LoopStatus, load_prompt

console = Console()


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


def get_output_path() -> Path:
    """Generate a unique output file path with timestamp."""
    OUTPUT_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return OUTPUT_DIR / f"{timestamp}.ndjson"


def setup_logging(verbose: bool = False) -> None:
    """Set up logging with rich handler."""
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True)],
    )


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    parser = argparse.ArgumentParser(
        prog="ralph-py",
        description="Python orchestrator for Claude Code CLI",
    )
    
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
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
        help="Maximum loop iterations (default: 10)",
    )
    run_parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Per-iteration timeout in seconds (default: 300)",
    )
    run_parser.add_argument(
        "--completion-marker",
        type=str,
        default="LOOP_COMPLETE",
        help="Marker to signal loop completion (default: LOOP_COMPLETE)",
    )
    run_parser.add_argument(
        "--single",
        action="store_true",
        help="Run single iteration (no loop)",
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
        default=300,
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
    console.print(Panel(
        Text(prompt[:500] + "..." if len(prompt) > 500 else prompt),
        title="[bold blue]Prompt[/bold blue]",
        border_style="blue",
    ))
    
    executor = ClaudeExecutor(backend, config)
    cli_started = False
    
    def on_text(text: str) -> None:
        nonlocal cli_started
        if not cli_started:
            console.print("[bold magenta]>>> claude CLI start >>>[/bold magenta]")
            cli_started = True
        console.print(f"[cyan]\\[msg][/cyan] {text}")
    
    def on_tool_call(name: str, tool_id: str, inputs: dict) -> None:
        nonlocal cli_started
        if not cli_started:
            console.print("[bold magenta]>>> claude CLI start >>>[/bold magenta]")
            cli_started = True
        detail = _get_tool_detail(name, inputs)
        console.print(f"[yellow]\\[{name}][/yellow]{detail}")
    
    result = await executor.run(
        prompt,
        on_text=on_text,
        on_tool_call=on_tool_call,
    )
    if cli_started:
        console.print("[bold magenta]<<< claude CLI end <<<[/bold magenta]\n")
    
    # Save NDJSON output to file
    if result.output:
        output_path = get_output_path()
        output_path.write_text(format_ndjson(result.output))
        console.print(f"[dim]NDJSON saved to: {output_path}[/dim]")
    
    # Print result summary
    if result.session_result:
        console.print(Panel(
            f"Duration: {result.session_result.duration_ms}ms\n"
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
    console.print(Panel(
        Text(prompt[:500] + "..." if len(prompt) > 500 else prompt),
        title="[bold blue]Initial Prompt[/bold blue]",
        border_style="blue",
    ))
    
    console.print(f"\n[dim]Max iterations: {config.max_iterations}[/dim]")
    console.print(f"[dim]Completion marker: {config.completion_marker}[/dim]\n")
    
    orchestrator = Orchestrator(backend, config)
    all_outputs: list[str] = []
    cli_started = False
    
    def on_iteration(iteration: int, result: ExecutionResult) -> None:
        nonlocal cli_started
        # End CLI section if started
        if cli_started:
            console.print("[bold magenta]<<< claude CLI end <<<[/bold magenta]")
            cli_started = False
        status = "[green]✓[/green]" if result.success else "[red]✗[/red]"
        console.print(f"\n[bold]Iteration {iteration}[/bold] {status}")
        if result.session_result:
            console.print(f"[dim]Cost: ${result.session_result.total_cost_usd:.4f}[/dim]")
        # Collect output for saving
        if result.output:
            all_outputs.append(result.output)
    
    def on_text(text: str) -> None:
        nonlocal cli_started
        if not cli_started:
            console.print("[bold magenta]>>> claude CLI start >>>[/bold magenta]")
            cli_started = True
        console.print(f"[cyan]\\[msg][/cyan] {text}")
    
    def on_tool_call(name: str, tool_id: str, inputs: dict) -> None:
        nonlocal cli_started
        if not cli_started:
            console.print("[bold magenta]>>> claude CLI start >>>[/bold magenta]")
            cli_started = True
        detail = _get_tool_detail(name, inputs)
        console.print(f"[yellow]\\[{name}][/yellow]{detail}")
    
    loop_result = await orchestrator.run(
        prompt,
        on_iteration=on_iteration,
        on_text=on_text,
        on_tool_call=on_tool_call,
    )
    # End CLI section if still open
    if cli_started:
        console.print("[bold magenta]<<< claude CLI end <<<[/bold magenta]\n")
    
    # Save NDJSON output to file
    if all_outputs:
        output_path = get_output_path()
        output_path.write_text(format_ndjson("\n".join(all_outputs)))
        console.print(f"[dim]NDJSON saved to: {output_path}[/dim]")
    
    # Print final summary
    status_emoji = {
        LoopStatus.COMPLETED: "[green]✓ Completed[/green]",
        LoopStatus.MAX_ITERATIONS: "[yellow]⚠ Max iterations reached[/yellow]",
        LoopStatus.TIMEOUT: "[red]⏱ Timeout[/red]",
        LoopStatus.INTERRUPTED: "[yellow]⚡ Interrupted[/yellow]",
        LoopStatus.ERROR: "[red]✗ Error[/red]",
    }.get(loop_result.status, str(loop_result.status))
    
    console.print(Panel(
        f"Status: {status_emoji}\n"
        f"Iterations: {loop_result.iterations}\n"
        f"Duration: {loop_result.total_duration_ms}ms\n"
        f"Total Cost: ${loop_result.total_cost_usd:.4f}",
        title="[bold]Loop Result[/bold]",
        border_style="blue" if loop_result.status == LoopStatus.COMPLETED else "yellow",
    ))
    
    if loop_result.error:
        console.print(f"[red]Error: {loop_result.error}[/red]")
    
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
                console.print("[bold magenta]>>> claude CLI start >>>[/bold magenta]")
                cli_started = True
            console.print(f"[cyan]\\[msg][/cyan] {text}")
        
        def on_tool_call(name: str, tool_id: str, inputs: dict) -> None:
            nonlocal cli_started
            if not cli_started:
                console.print("[bold magenta]>>> claude CLI start >>>[/bold magenta]")
                cli_started = True
            detail = _get_tool_detail(name, inputs)
            console.print(f"[yellow]\\[{name}][/yellow]{detail}")
        
        result = await executor.run(
            prompt,
            on_text=on_text,
            on_tool_call=on_tool_call,
        )
    
    if cli_started:
        console.print("[bold magenta]<<< claude CLI end <<<[/bold magenta]\n")
    
    # Save NDJSON output to file
    if result.output:
        output_path = get_output_path()
        output_path.write_text(format_ndjson(result.output))
        console.print(f"[dim]NDJSON saved to: {output_path}[/dim]")
    
    return 0


def main() -> int:
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 0
    
    setup_logging(args.verbose)
    
    try:
        if args.command == "run":
            # Get prompt
            if args.prompt:
                prompt = args.prompt
            else:
                try:
                    prompt = load_prompt(args.file, args.directory)
                except FileNotFoundError as e:
                    console.print(f"[red]Error: {e}[/red]")
                    return 0
            
            # Create backend
            backend = ClaudeBackend.default()
            
            if args.single:
                # Single execution
                config = ExecutorConfig(
                    idle_timeout_secs=args.timeout,
                    working_directory=args.directory,
                )
                return asyncio.run(run_single(prompt, backend, config))
            else:
                # Loop execution
                config = OrchestratorConfig(
                    max_iterations=args.max_iterations,
                    iteration_timeout_secs=args.timeout,
                    completion_marker=args.completion_marker,
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
        console.print("\n[yellow]Interrupted[/yellow]")
        return 0
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        if args.verbose:
            console.print_exception()
        return 0


if __name__ == "__main__":
    sys.exit(main())
