"""
Exceptions used by ralph-sq.
"""


class RalphExitRequested(Exception):
    """Raised when the model invokes a Bash command starting with 'ralph-sq exit' to exit the current loop."""


class RalphContinueRequested(Exception):
    """Raised when the model invokes a Bash command starting with 'ralph-sq continue' to skip the current step and continue the loop."""
