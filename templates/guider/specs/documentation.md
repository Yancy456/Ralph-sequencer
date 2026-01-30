## Commands

### `run`
`run` is the primary command that drives Ralph through the chosen workflow. It accepts several modifiers:

- `-l, --lang`: limit execution to help text localized in either `en` or `zh`.
- `-m, --max-iterations`: number of iterations Ralph should perform before stopping (defaults to `1`).
- `--timeout`: maximum time (in seconds) that each prompt cycle is allowed to run; `0` disables the timeout.
- `-C, --directory`: path to the workspace that Ralph should analyze instead of the current directory.
- `-c, --config`: YAML configuration file to load; when not provided it defaults to `ralph.yaml`, but you can pass `--config` without a value to force the default.
- `-p, --prompt`: override the template prompt that would normally be selected via the configuration.
- `-r, --resume`: continue a previously interrupted workflow if a checkpoint is available.

### `exit`
Stops the current Ralph session immediately; useful for terminating interactive loops or canceling running commands.

### `continue`
`continue` tells it to move on and skip the current step.

### `update`
Fetches the latest Ralph resources; in most cases it re-downloads the builtin templates, prompts, and tooling Ralph needs to function.

### `config`
Manipulate Ralph's persistent settings:

- `config lang [value]`: set or display the default locale used for help messages and prompts. Acceptable values are `en`, `zh`, or `cn`.
- `config show`: dump the currently saved configuration values (language, workspace preferences, etc.).

### `template`
`template <name>` lets you inspect or scaffold a specific template by name. Provide the template key exactly as it appears in `/templates`.