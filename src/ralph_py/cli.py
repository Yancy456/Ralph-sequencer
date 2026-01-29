#!/usr/bin/env python3
"""
CLI entry point for ralph-py.

Usage:
    ralph-py run --config              # Run with ralph.yaml
    ralph-py run --config <path>       # Run with custom config file
"""

import argparse
import asyncio
import shutil
import json
import logging
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

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


def format_duration(ms: int) -> str:
    """Format duration in milliseconds to HH:MM:SS format."""
    total_seconds = ms // 1000
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

from rich.panel import Panel
import re

from ralph_py.config import RalphConfig, Role, RepeatSequence, SequenceStep
from ralph_py.exceptions import RalphExitRequested, RalphContinueRequested
from ralph_py.executor import ExecutionResult
from ralph_py.orchestrator import Orchestrator, OrchestratorConfig, LoopStatus
from ralph_py.stream_parser import (
    ClaudeStreamParser,
    AssistantEvent,
    TextContent,
    ToolUseContent,
)
from ralph_py.logging_system import (
    console,
    log_print,
    log_print_exception,
    setup_logging,
    set_run_id,
    get_run_id,
    get_run_dir,
)


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
    elif name == "Task":
        subagent_type = inputs.get("subagent_type", "")
        prompt = inputs.get("prompt", "")
        detail = f" [{subagent_type}]"
        if prompt:
            # Clean up prompt for display: join lines and truncate
            clean_prompt = " ".join(prompt.splitlines()).strip()
            if len(clean_prompt) > 80:
                detail += f" {clean_prompt[:80]}..."
            else:
                detail += f" {clean_prompt}"
        return detail
    return ""


def get_output_path(iteration: Optional[int] = None) -> Path:
    """Generate output file path in the current run directory."""
    run_dir = get_run_dir()
    if iteration is not None:
        return run_dir / f"iteration_{iteration}.ndjson"
    return run_dir / "output.ndjson"


def save_config_snapshot(config_path: Path) -> Path:
    """Save a copy of the current config file into the run directory."""
    run_dir = get_run_dir()
    snapshot_name = config_path.name
    snapshot_path = run_dir / snapshot_name
    try:
        shutil.copy2(config_path, snapshot_path)
    except Exception:
        # Best-effort; don't fail the run if snapshot fails
        _logger = logging.getLogger(__name__)
        _logger.warning("Failed to save config snapshot to %s", snapshot_path)
    return snapshot_path


def save_iteration_state(
    config_path: Path,
    iteration: int,
    step_info: str,
    role: str,
) -> None:
    """Persist current iteration position for potential resume."""
    run_dir = get_run_dir()
    state_path = run_dir / "state.json"
    state = {
        "config_path": str(config_path),
        "run_id": get_run_id(),
        "iteration": iteration,
        "step_info": step_info,
        "role": role,
        "timestamp": datetime.now().isoformat(),
    }
    try:
        with state_path.open("w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        _logger = logging.getLogger(__name__)
        _logger.warning("Failed to save iteration state to %s", state_path)


def load_last_state() -> Optional[dict]:
    """Load the most recent iteration state from the latest run directory."""
    if not OUTPUT_DIR.exists():
        return None
    
    run_dirs = [d for d in OUTPUT_DIR.iterdir() if d.is_dir()]
    if not run_dirs:
        return None
    
    # Sort by modification time, newest first
    run_dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    
    for run_dir in run_dirs:
        state_path = run_dir / "state.json"
        if state_path.exists():
            try:
                with state_path.open("r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                _logger = logging.getLogger(__name__)
                _logger.warning("Failed to read state file from %s", state_path)
                continue
    return None


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
    run_parser.add_argument(
        "-p", "--prompt",
        type=str,
        help="Run a single iteration with an inline prompt using a default role (quick test mode)",
    )
    run_parser.add_argument(
        "-r", "--resume",
        action="store_true",
        help="Resume from the last saved iteration state (if available)",
    )

    # Exit command
    subparsers.add_parser("exit", help="Terminate ralph-py")

    # Continue command (skip current step, continue loop when invoked via Bash during run)
    subparsers.add_parser("continue", help="Skip current step and continue to next (when invoked during run)")

    return parser


async def run_sequences(
    ralph_config: RalphConfig,
    config: OrchestratorConfig,
    config_path: Path,
) -> int:
    """Run sequences from configuration."""
    logger = logging.getLogger(__name__)
    
    orchestrator = Orchestrator(config)
    cli_started = False
    
    def on_iteration_start(
        iteration: int,
        sequence_info: str,
        step_info: str,
        role: str,
        prompt_preview: str,
    ) -> None:
        """Display iteration start information in a panel."""
        # Pre-compute NDJSON path (same as used when streaming starts)
        output_path = get_output_path(iteration)
        # Save current iteration state for potential resume
        save_iteration_state(config_path, iteration, step_info, role)
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
            f"Role: [yellow]{role}[/yellow]",
            f"Prompt: {prompt_preview}" if prompt_preview else "Prompt: (empty)",
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
    
    # Track open file handles for real-time NDJSON output
    ndjson_files: dict[int, any] = {}
    
    def on_raw_line(iteration: int, line: str) -> None:
        """Process raw NDJSON line for file logging and real-time display."""
        if iteration not in ndjson_files:
            output_path = get_output_path(iteration)
            ndjson_files[iteration] = open(output_path, 'w', encoding='utf-8')
        
        line = line.strip()
        if not line:
            return

        # 1. Write to debug file
        try:
            obj = json.loads(line)
            formatted = json.dumps(obj, indent=2, ensure_ascii=False)
            ndjson_files[iteration].write(formatted + '\n\n')
        except json.JSONDecodeError:
            ndjson_files[iteration].write(line + '\n')
        ndjson_files[iteration].flush()

        # 2. Parse and display content/tool calls
        event = ClaudeStreamParser.parse_line(line)
        if event:
            # Handle subagent display
            agent_prefix = ""
            if getattr(event, "parent_tool_use_id", None):
                parent_id = event.parent_tool_use_id
                short_id = parent_id
                if parent_id.startswith("call_"):
                    short_id = parent_id[5:9]
                elif len(parent_id) > 4:
                    short_id = parent_id[:4]
                agent_prefix = f"[magenta]\\[agent {short_id}][/magenta] "

            if isinstance(event, AssistantEvent):
                for block in event.message.content:
                    if isinstance(block, TextContent):
                        log_print(f"{agent_prefix}[cyan]\\[msg][/cyan] {block.text}")
                    elif isinstance(block, ToolUseContent):
                        detail = _get_tool_detail(block.name, block.input)
                        log_print(f"{agent_prefix}[yellow]\\[{block.name}][/yellow]{detail}")
                        if block.name == "Bash":
                            cmd = (block.input.get("command") or "").strip()
                            if cmd.startswith("ralph-py exit"):
                                raise RalphExitRequested
                            if cmd.startswith("ralph-py continue"):
                                raise RalphContinueRequested
        else:
            # For non-JSON output (plain text mode), treat as message
            if not line.startswith('{'):
                log_print(f"[cyan]\\[msg][/cyan] {line}")
    
    def on_save_output(iteration: int, output: str) -> None:
        """Close file handle after iteration."""
        if iteration in ndjson_files:
            ndjson_files[iteration].close()
            del ndjson_files[iteration]
    
    loop_result = await orchestrator.run_sequences(
        ralph_config,
        on_iteration=on_iteration,
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
        LoopStatus.RALPH_EXIT_REQUESTED: "[green]✓ RalphExitRequested[/green]",
        LoopStatus.RALPH_CONTINUE_REQUESTED: "[green]✓ RalphContinueRequested[/green]",
    }.get(loop_result.status, str(loop_result.status))
    
    duration_str = format_duration(loop_result.total_duration_ms)
    log_print(Panel(
        f"Status: {status_emoji}\n"
        f"Iterations: {loop_result.iterations}\n"
        f"Duration: {duration_str}\n"
        f"Total Cost: ${loop_result.total_cost_usd:.4f}",
        title="[bold]Sequence Execution Result[/bold]",
        border_style=(
            "blue"
            if loop_result.status == LoopStatus.COMPLETED
            else "yellow"
        ),
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
        if args.command == "exit":
            console.print("ralph-py has been terminated")
            return 0
        if args.command == "continue":
            console.print("ralph-py continue (skips current step when invoked via Bash during run)")
            return 0
        if args.command == "run":
            # Quick prompt mode: run a single iteration with an inline prompt
            if args.prompt:
                if args.config:
                    log_print("[yellow]Warning: --prompt provided; ignoring --config and using inline prompt only[/yellow]")
                
                # Build an in-memory config with a single default role and one sequence
                default_role = Role(name="default")
                step = SequenceStep(role="default", prompt=args.prompt, new_session=True)
                repeat_seq = RepeatSequence(steps=[step], repeat=1)
                ralph_config = RalphConfig(
                    roles={"default": default_role},
                    repeat_sequences=[repeat_seq],
                )
                
                # Use a synthetic config path for state tracking
                config_path = Path("INLINE_PROMPT")
                
                log_print(Panel(
                    "Running single iteration with inline prompt",
                    title="[bold blue]Quick Prompt Run[/bold blue]",
                    border_style="blue",
                ))
            else:
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
                
                # Save a snapshot of the configuration for this run
                snapshot_path = save_config_snapshot(config_path)
                
                log_print(Panel(
                    f"Loaded {len(ralph_config.repeat_sequences)} sequence(s) from configuration",
                    title="[bold blue]Configuration Loaded[/bold blue]",
                    border_style="blue",
                ))
            
            # Determine resume point if requested
            resume_from_iteration = 0
            if args.resume and not args.prompt:
                state = load_last_state()
                if state:
                    state_config = Path(state.get("config_path", ""))
                    state_iter = state.get("iteration", 0)
                    if state_config == config_path and isinstance(state_iter, int) and state_iter > 0:
                        resume_from_iteration = max(0, state_iter - 1)
                        log_print(f"[yellow]Resuming from iteration {state_iter} using state in {state_config}[/yellow]")
                    else:
                        log_print("[yellow]No compatible state found to resume from; starting from beginning.[/yellow]")
                else:
                    log_print("[yellow]No previous state found; starting from beginning.[/yellow]")
            
            # Orchestrator config
            orchestrator_config = OrchestratorConfig(
                max_iterations=args.max_iterations,
                iteration_timeout_secs=args.timeout,
                working_directory=args.directory,
                resume_from_iteration=resume_from_iteration,
                session_id=run_id,
            )
            
            # Run sequences
            return asyncio.run(run_sequences(ralph_config, orchestrator_config, config_path))
        
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
