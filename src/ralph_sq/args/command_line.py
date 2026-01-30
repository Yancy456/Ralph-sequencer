import argparse


from ralph_sq.settings.persistence import get_setting


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    parser = argparse.ArgumentParser(
        prog="ralph-sq",
        description="Python orchestrator for Claude Code CLI",
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    # Run command
    run_parser = subparsers.add_parser("run", help="Run Claude with configuration file")
    run_parser.add_argument(
        "-l", "--lang",
        type=str,
        choices=["en", "zh"],
        help=f"Language for display (default: {get_setting('language', 'en')})",
    )
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
    subparsers.add_parser("exit", help="Terminate ralph-sq")

    # Continue command (skip current step, continue loop when invoked via Bash during run)
    subparsers.add_parser("continue", help="Skip current step and continue to next (when invoked during run)")

    # Config command
    config_parser = subparsers.add_parser("config", help="Manage persistent settings")
    config_parser.add_argument(
        "-l", "--lang",
        type=str,
        choices=["en", "zh"],
        help=f"Set default language for display (current: {get_setting('language', 'en')})",
    )

    return parser
