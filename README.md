# Ralph-sequencer

Ralph-sequencer is an agent orchestrator for the Claude Code CLI. 


It organizes agents in liner and loop sequences. which allows you to create multi-agent systems simply. With Ralph-sequencer, you can automate your daily tasks in a reproducible and reliable manner.

## Features

- **Use Native Claude Code CLI**: Ralph-sequencer uses your system CC CLI to run with additional functions, like logging sysytem and agent orchestrator provided. That means you can use Ralph-sequencer as same as you use CC CLI. 
- **Ralph-loop Support**: Ralph-sequencer supports loop sequences. You can use it to automate your daily tasks in a reproducible and reliable manner. The biggest difference between Ralph-sequencer and other Ralph project is that Ralph-sequencer supports loop sequences.
- **Project Template Support**: Ralph-sequencer provides a project template to help you get started quickly. You can use others templates to bootstrap your project.

## Requirements

- Python 3.10+
- Claude Code CLI

## Installation

```bash
cd ralph_sq
pip install -e .
```

## Usage

### Command Line

```bash
# 使用内联 prompt 运行
ralph-sq run -p "Create a hello world Python script"

# 从 PROMPT.md 文件运行
ralph-sq run

# 从自定义文件运行
ralph-sq run -f my_prompt.txt

# 指定工作目录
ralph-sq run -p "Fix the bug" -C /path/to/project

# 恢复最近对话或指定 UUID
ralph-sq run -r
ralph-sq run -r 550e8400-e29b-41d4-a716-446655440000
```




## How It Works

Ralph-Py 通过以下方式运行 Claude Code CLI：

```bash
claude --dangerously-skip-permissions --verbose --output-format stream-json -p "your prompt"
```



## License

MIT
