import argparse


from ralph_sq.settings.persistence import get_setting
from ralph_sq.i18n import _


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    parser = argparse.ArgumentParser(
        prog="ralph-sq",
        description=_("help.description"),
    )
    
    subparsers = parser.add_subparsers(dest="command", help=_("help.commands"))
    
    # Run command
    run_parser = subparsers.add_parser("run", help=_("help.run_help"))
    run_parser.add_argument(
        "-l", "--lang",
        type=str,
        choices=["en", "zh"],
        help=_("help.run_lang", lang=get_setting("language", "en")),
    )
    run_parser.add_argument(
        "-m", "--max-iterations",
        type=int,
        default=1,
        help=_("help.run_max_iterations"),
    )
    run_parser.add_argument(
        "--timeout",
        type=int,
        default=0,
        help=_("help.run_timeout"),
    )
    run_parser.add_argument(
        "-C", "--directory",
        type=str,
        help=_("help.run_directory"),
    )
    run_parser.add_argument(
        "-c", "--config",
        type=str,
        nargs="?",
        const="ralph.yaml",
        default="ralph.yaml",
        help=_("help.run_config"),
    )
    run_parser.add_argument(
        "-p", "--prompt",
        type=str,
        help=_("help.run_prompt"),
    )
    run_parser.add_argument(
        "-r", "--resume",
        action="store_true",
        help=_("help.run_resume"),
    )

    # Exit command
    subparsers.add_parser("exit", help=_("help.exit_help"))

    # Continue command (skip current step, continue loop when invoked via Bash during run)
    subparsers.add_parser("continue", help=_("help.continue_help"))

    # Update command
    subparsers.add_parser("update", help=_("help.update_help"))

    # Config command
    config_parser = subparsers.add_parser("config", help=_("help.config_help"))
    config_subparsers = config_parser.add_subparsers(dest="config_item", help=_("help.config_items"))
    
    # Config lang
    lang_parser = config_subparsers.add_parser("lang", help=_("help.config_lang_help"))
    lang_parser.add_argument(
        "value",
        nargs="?",
        choices=["en", "zh", "cn"],
        help=_("help.config_lang_value", lang=get_setting("language", "en")),
    )

    # Config show
    config_subparsers.add_parser("show", help=_("help.config_show_help"))

    # Template command
    template_parser = subparsers.add_parser("template", help=_("help.template_help"))
    template_parser.add_argument(
        "name",
        help=_("help.template_name"),
    )

    return parser
