import asyncio
import sys
import uuid
import subprocess
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
from rich.prompt import Confirm


def main() -> int:
    """Main entry point."""
    # 1. Initialize language from persistent settings as early as possible
    initial_lang = get_setting("language", "en")
    i18n.set_language(initial_lang)

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
            if args.config_item == "lang":
                if args.value:
                    lang_value = "zh" if args.value == "cn" else args.value
                    set_setting("language", lang_value)
                    i18n.set_language(lang_value)
                    console.print(_("cli.setting_updated", key="language", value=lang_value))
                else:
                    lang = get_setting("language", "en")
                    console.print(_("cli.current_setting", key="language", value=lang))
            elif args.config_item == "show":
                from ralph_sq.settings.persistence import SETTINGS_FILE
                config_path = SETTINGS_FILE
                if config_path.exists():
                    from rich.syntax import Syntax
                    console.print(_("cli.config_path", path=str(config_path)))
                    with open(config_path, "r", encoding="utf-8") as f:
                        content = f.read()
                        syntax = Syntax(content, "yaml", theme="monokai", line_numbers=True)
                        console.print(syntax)
                else:
                    console.print(_("cli.config_not_found", path=str(config_path)))
            else:
                parser.print_help()
            return 0
        if args.command == "template":
            import yaml
            import shutil
            import glob
            import fnmatch
            
            template_name = args.name
            
            # Find templates directory
            # Try 1: Next to ralph_sq package (dev mode)
            # Try 2: Inside ralph_sq package (if we decide to move it later)
            possible_paths = [
                Path(__file__).parent.parent.parent / "templates" / template_name,
                Path(__file__).parent / "templates" / template_name,
            ]
            
            template_path = None
            for p in possible_paths:
                if p.exists() and p.is_dir():
                    template_path = p
                    break
            
            if not template_path:
                console.print(_("cli.template_not_found", name=template_name, path=str(possible_paths[0])))
                return 1
            
            install_yaml_path = template_path / "install.yaml"
            if not install_yaml_path.exists():
                console.print(_("cli.error", error=f"install.yaml not found in {template_path}"))
                return 1
            
            if not Confirm.ask(_("cli.template_confirm", name=template_name), default=False):
                console.print(_("cli.template_cancelled"))
                return 0
                
            console.print(_("cli.template_installing", name=template_name))
            
            try:
                with open(install_yaml_path, "r", encoding="utf-8") as f:
                    install_config = yaml.safe_load(f)
                
                copy_files = install_config.get("copy_files", [])
                
                # Ensure install.yaml itself is also copied if not already included
                if "install.yaml" not in copy_files and not any(fnmatch.fnmatch("install.yaml", p) for p in copy_files):
                    copy_files.append("install.yaml")

                for pattern in copy_files:
                    # Resolve glob patterns relative to template_path
                    files_to_copy = []
                    if "*" in pattern:
                        search_pattern = str(template_path / pattern)
                        files_to_copy = glob.glob(search_pattern, recursive=True)
                    else:
                        file_path = template_path / pattern
                        if file_path.exists():
                            files_to_copy = [str(file_path)]
                    
                    for src_path_str in files_to_copy:
                        src_path = Path(src_path_str)
                            
                        # Calculate relative path to maintain directory structure
                        rel_path = src_path.relative_to(template_path)
                        dest_path = Path.cwd() / rel_path
                        
                        # Create parent directories if they don't exist
                        dest_path.parent.mkdir(parents=True, exist_ok=True)
                        
                        if src_path.is_dir():
                            # If it's a directory, we skip it here as glob might return it, 
                            # and we'll handle files inside it via other patterns or recursive glob
                            continue
                        
                        console.print(_("cli.template_copying", src=str(rel_path), dest=str(dest_path.relative_to(Path.cwd()))))
                        shutil.copy2(src_path, dest_path)
                
                console.print(_("cli.template_installed", name=template_name))
                console.print(f"[blue]{_('cli.template_run_hint')}[/blue]")
                return 0
            except Exception as e:
                console.print(_("cli.template_error", error=str(e)))
                return 1

        if args.command == "update":
            console.print(_("cli.update_start"))
            
            # Check if git is available
            try:
                subprocess.run(["git", "--version"], capture_output=True, check=True)
            except (subprocess.CalledProcessError, FileNotFoundError):
                console.print(f"[red]{_('cli.git_not_found')}[/red]")
                return 1
            
            # Get the project root (where .git should be)
            project_root = Path(__file__).parent.parent.parent
            if not (project_root / ".git").exists():
                console.print(f"[red]{_('cli.not_a_git_repo')}[/red]")
                return 1
            
            try:
                # Run git pull
                process = subprocess.run(
                    ["git", "pull"], 
                    cwd=project_root, 
                    capture_output=True, 
                    text=True, 
                    check=True
                )
                console.print(process.stdout)
                console.print(f"[green]{_('cli.update_success')}[/green]")
                return 0
            except subprocess.CalledProcessError as e:
                console.print(f"[red]{_('cli.update_error', error=e.stderr)}[/red]")
                return 1

        if args.command == "run":
            # Set language from CLI if specified
            if args.lang:
                i18n.set_language(args.lang)

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
                config_file = args.config
                
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
