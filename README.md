# Ralph-sequencer

Ralph-sequencer is an agent orchestrator for the Claude Code CLI. 

It organizes agents in linear and loop sequences, allowing you to create multi-agent systems simply. With Ralph-sequencer, you can automate your daily tasks in a reproducible and reliable manner.

## Features

- **Use Native Claude Code CLI**: Ralph-sequencer uses your system's `claude` CLI with additional functions like a logging system and agent orchestrator.
- **Ralph-loop Support**: Supports complex loop sequences for automation.
- **Project Template Support**: Provides templates to help you bootstrap projects quickly.
- **Persistent Settings**: Remembers your preferred language and other settings.

## Requirements

- Python 3.10+
- [Claude Code CLI](https://github.com/anthropics/claude-code)

## Installation

```bash
# Clone the repository
git clone https://github.com/your-repo/ralph-python.git
cd ralph-python

# Use the install script
python install.py
```

## Uninstallation

To remove the package and optionally clean up settings:

```bash
# Standard uninstall
python uninstall.py

# Full uninstall (removes settings and debug files)
python uninstall.py --full
```

## Usage

### Configuration

You can set your preferred language:

```bash
# Set to Chinese
ralph-sq config lang cn

# Set to English
ralph-sq config lang en

# View current settings
ralph-sq config lang
```

### Running Sequences

```bash
# Run with an inline prompt (quick test)
ralph-sq run -p "Create a hello world Python script"

# Run with default ralph.yaml
ralph-sq run -c

# Run with custom config file
ralph-sq run -c my_config.yaml

# Run with specified max iterations
ralph-sq run -c -m 5

# Specify working directory
ralph-sq run -p "Fix the bug" -C /path/to/project

# Resume from the last saved state
ralph-sq run -c -r
```

## How It Works

Ralph-sequencer runs the Claude Code CLI with optimal parameters:

```bash
claude --dangerously-skip-permissions --verbose --output-format stream-json -p "your prompt"
```

## License

MIT
