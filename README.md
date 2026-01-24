# Ralph-Py

Python implementation of Ralph orchestrator for Claude Code CLI.

## Overview

Ralph-Py 是 Rust 版本 [ralph-orchestrator](../ralph-orchestrator) 的 Python 移植版本。它提供了一个简洁的 Python 接口来运行和编排 Claude Code CLI。

## Features

- **Claude CLI 封装**: 通过子进程运行 Claude Code CLI
- **NDJSON 流解析**: 实时解析 `--output-format stream-json` 输出
- **编排循环**: 支持迭代执行直到完成标记出现

## Requirements

- Python 3.10+
- Claude Code CLI (需要先安装并登录: `claude /login`)

## Installation

```bash
cd ralph_py
pip install -e .
```

Or with development dependencies:

```bash
pip install -e ".[dev]"
```

## Usage

### Command Line

```bash
# 使用内联 prompt 运行
ralph-py run -p "Create a hello world Python script"

# 从 PROMPT.md 文件运行
ralph-py run

# 从自定义文件运行
ralph-py run -f my_prompt.txt

# 单次执行（不循环）
ralph-py run -p "List files" --single

# 指定工作目录
ralph-py run -p "Fix the bug" -C /path/to/project

# 流式输出
ralph-py stream -p "Explain this code"
```



## Architecture

```
ralph_py/
├── src/ralph_py/
│   ├── __init__.py          # Package exports
│   ├── claude_backend.py    # CLI backend configuration
│   ├── stream_parser.py     # NDJSON stream parsing
│   ├── executor.py          # Subprocess execution
│   ├── orchestrator.py      # Loop orchestration
│   └── cli.py               # CLI entry point
├── pyproject.toml           # Project configuration
└── README.md               # This file
```

## How It Works

Ralph-Py 通过以下方式运行 Claude Code CLI：

```bash
claude --dangerously-skip-permissions --verbose --output-format stream-json -p "your prompt"
```

关键参数说明：
- `--dangerously-skip-permissions`: 跳过权限确认（自动模式必需）
- `--verbose`: 启用详细输出
- `--output-format stream-json`: 输出 NDJSON 格式便于解析
- `-p`: 以非交互模式传递 prompt

## Configuration

### ExecutorConfig

| 参数 | 默认值 | 说明 |
|-----|--------|------|
| `idle_timeout_secs` | 300 | 空闲超时时间（秒） |
| `working_directory` | None | 工作目录 |

### OrchestratorConfig

| 参数 | 默认值 | 说明 |
|-----|--------|------|
| `max_iterations` | 10 | 最大循环次数 |
| `loop_timeout_secs` | 3600 | 总超时时间（秒） |
| `iteration_timeout_secs` | 300 | 单次迭代超时（秒） |
| `break_marker` | "LOOP_BREAK" | 中断标记 |

## License

MIT
