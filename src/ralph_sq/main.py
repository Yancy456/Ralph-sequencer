import asyncio
import sys
import uuid
from pathlib import Path

from ralph_sq.args.command_line import create_parser
from ralph_sq.config import RalphConfig, Role, RepeatSequence, SequenceStep
from ralph_sq.i18n import _, i18n
from ralph_sq.logging_system import (
    console,
    log_print,
    log_print_exception,
    setup_logging,
    set_run_id,
)
from ralph_sq.orchestrator import OrchestratorConfig
from ralph_sq.settings.persistence import get_setting, set_setting
from ralph_sq.cli import run_sequences, save_config_snapshot, load_last_state

from rich.panel import Panel


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
            console.print(_("cli.terminated"))
            return 0
        if args.command == "continue":
            console.print(_("cli.continue_skip"))
            return 0
        if args.command == "config":
            if args.lang:
                set_setting("language", args.lang)
                i18n.set_language(args.lang)
                console.print(_("cli.setting_updated", key="language", value=args.lang))
            else:
                lang = get_setting("language", "en")
                console.print(_("cli.current_setting", key="language", value=lang))
            return 0
        if args.command == "run":
            # Set language priority: CLI > Persistent Settings > Default "en"
            current_lang = args.lang or get_setting("language", "en")
            i18n.set_language(current_lang)
            
            # If explicitly provided via CLI, persist it
            if args.lang:
                set_setting("language", args.lang)

            # Quick prompt mode: run a single iteration with an inline prompt
            if args.prompt:
                if args.config:
                    log_print(f"[yellow]{_('cli.warning_prompt_config')}[/yellow]")
                
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
                    _("cli.running_inline"),
                    title=f"[bold blue]{_('cli.quick_prompt_run')}[/bold blue]",
                    border_style="blue",
                ))
            else:
                # Check if using config file
                # If --config is provided without value, use default "ralph.yaml"
                config_file = args.config if args.config else None
                if not config_file:
                    log_print(f"[red]{_('cli.error_config_required')}[/red]")
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
                    
                    # Language from config if not specified via CLI
                    if not args.lang and ralph_config.language:
                        i18n.set_language(ralph_config.language)
                        
                except FileNotFoundError as e:
                    log_print(f"[red]{_('cli.error', error=str(e))}[/red]")
                    return 0
                except Exception as e:
                    log_print(f"[red]{_('cli.error_loading_config', error=str(e))}[/red]")
                    log_print_exception()
                    return 0
                
                if not ralph_config.repeat_sequences:
                    log_print(f"[yellow]{_('cli.warning_no_sequences')}[/yellow]")
                    return 0
                
                # Save a snapshot of the configuration for this run
                save_config_snapshot(config_path)
                
                log_print(Panel(
                    _("cli.loaded_sequences", count=len(ralph_config.repeat_sequences)),
                    title=f"[bold blue]{_('cli.configuration_loaded')}[/bold blue]",
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
                        log_print(f"[yellow]{_('cli.resuming_iteration', iteration=state_iter, config=state_config)}[/yellow]")
                    else:
                        log_print(f"[yellow]{_('cli.no_compatible_state')}[/yellow]")
                else:
                    log_print(f"[yellow]{_('cli.no_previous_state')}[/yellow]")
            
            # Orchestrator config
            orchestrator_config = OrchestratorConfig(
                max_iterations=args.max_iterations,
                iteration_timeout_secs=args.timeout,
                working_directory=args.directory,
                resume_from_iteration=resume_from_iteration,
                session_id=run_id,
                disallowed_tools=["AskUserQuestion"],
            )
            
            # Run sequences
            return asyncio.run(run_sequences(ralph_config, orchestrator_config, config_path))
        
        else:
            parser.print_help()
            return 0
            
    except KeyboardInterrupt:
        log_print(f"\n[yellow]{_('cli.interrupted')}[/yellow]")
        return 0
    except Exception as e:
        log_print(f"[red]{_('cli.error', error=str(e))}[/red]")
        log_print_exception()
        return 0


if __name__ == "__main__":
    sys.exit(main())
