#!/usr/bin/env python3
"""
CLI Monitor for ralph-sq.

"""

import asyncio
import shutil
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from rich.panel import Panel

from ralph_sq.config import RalphConfig
from ralph_sq.i18n import _, i18n
from ralph_sq.exceptions import RalphExitRequested, RalphContinueRequested
from ralph_sq.executor import ExecutionResult
from ralph_sq.orchestrator import Orchestrator, OrchestratorConfig, LoopStatus
from ralph_sq.stream_parser import (
    ClaudeStreamParser,
    AssistantEvent,
    TextContent,
    ToolUseContent,
)
from ralph_sq.logging_system import (
    log_print,
    get_run_id,
    get_run_dir,
)

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
    elif name == "TodoWrite" and "todos" in inputs:
        todos = inputs["todos"]
        if not todos:
            return ""
        # 1. Look for in_progress
        in_progress_todos = [t for t in todos if t.get("status") == "in_progress"]
        if in_progress_todos:
            # Output in_progress content
            content = in_progress_todos[0].get("content") or in_progress_todos[0].get("activeForm") or ""
            return f" {content}"
        # 2. No in_progress, output first three in one line
        top_three = []
        for t in todos[:3]:
            c = t.get("content") or t.get("activeForm") or ""
            if c:
                top_three.append(c)
        if top_three:
            return f" {' | '.join(top_three)}"
        return ""
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
        highlighted_step_info = _("cli.progress", info=highlighted_step_info)
        lines = []
        if sequence_info:
            lines.append(sequence_info)
        
        prompt_preview_val = prompt_preview if prompt_preview else _("cli.prompt_empty")
        memory_status = _("cli.memory_disabled")
        
        lines.extend([
            highlighted_step_info,
            _("cli.role", role=f"[yellow]{role}[/yellow]"),
            _("cli.prompt", prompt=prompt_preview_val),
            _("cli.memory", status=f"[red]{memory_status}[/red]")
        ])
        content = "\n".join(lines)
        log_print(Panel(
            content,
            title=f"[bold green]{_('cli.iteration_start', iteration=iteration)}[/bold green]",
            border_style="green",
        ))
    
    def on_iteration(iteration: int, result: ExecutionResult) -> None:
        status = "✓" if result.success else "✗"
        lines = [f"[bold]{_('cli.iteration_result', iteration=iteration)}[/bold] {status}"]
        if result.session_result:
            duration_str = format_duration(result.session_result.duration_ms)
            lines.append(f"[dim]{_('cli.cost', cost=f'{result.session_result.total_cost_usd:.4f}')}[/dim]")
            lines.append(f"[dim]{_('cli.duration', duration=duration_str)}[/dim]")
        content = "\n".join(lines)
        log_print(Panel(
            content,
            title=f"[bold blue]{_('cli.iteration_result', iteration=iteration)}[/bold blue]",
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
                            if cmd.startswith("ralph-sq exit"):
                                raise RalphExitRequested
                            if cmd.startswith("ralph-sq continue"):
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
        LoopStatus.COMPLETED: _("status.completed"),
        LoopStatus.MAX_ITERATIONS: _("status.max_iterations"),
        LoopStatus.TIMEOUT: _("status.timeout"),
        LoopStatus.INTERRUPTED: _("status.interrupted"),
        LoopStatus.ERROR: _("status.error"),
        LoopStatus.RALPH_EXIT_REQUESTED: _("status.exit_requested"),
        LoopStatus.RALPH_CONTINUE_REQUESTED: _("status.continue_requested"),
    }.get(loop_result.status, str(loop_result.status))
    
    duration_str = format_duration(loop_result.total_duration_ms)
    log_print(Panel(
        f"{_('cli.status', status=status_emoji)}\n"
        f"{_('cli.iterations', count=loop_result.iterations)}\n"
        f"{_('cli.duration', duration=duration_str)}\n"
        f"{_('cli.total_cost', cost=f'{loop_result.total_cost_usd:.4f}')}",
        title=f"[bold]{_('cli.sequence_execution_result')}[/bold]",
        border_style=(
            "blue"
            if loop_result.status == LoopStatus.COMPLETED
            else "yellow"
        ),
    ))
    
    if loop_result.error:
        log_print(f"[red]{_('cli.error', error=loop_result.error)}[/red]")
    
    return 0
