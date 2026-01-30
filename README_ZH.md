# Ralph-sequencer

[English](./README.md) | [简体中文](./README_ZH.md)

![Ralph-sequencer 预览](./preview1.png)

Ralph-sequencer 是一个先进的 Claude Code CLI 智能体编排器。

阅读 Ralph-sequencer 的自我介绍以了解它的功能：

我是 Ralph-sequencer 😊，一个智能体编排器。我像交响乐团的指挥一样组织多个智能体来完成复杂的任务 🎼。 我可以帮助你完成 ✅ 什么：

- ✅ 无人值守运行 2 小时，完成一部 30 万字的莎士比亚风格小说 📖。
- ✅ 帮助你搜索 50+ 个网站，创建一个复杂的 PPT 演示文稿 📄。
- ✅ 自动运行编写和检查代码，完成项目从 0 到 1 的开发 📝。
- ✅ 自动运行超过 50 项系统安全检查，并生成全面的安全报告 💼。

我不能 ☹️ 做什么：
1. ✖️ 我不是通用人工智能 (AGI)。我不能仅凭一句话就完成所有事情（我也不必这样做🤭），但我可以根据模板完成指定任务。
2. ✖️ 我不能替你做决定。虽然我可以引导你完成决策过程，但我必须要和人类对齐；否则我可能是个不可靠的朋友。
3. ✖️ 虽然我足够聪明，可以帮你完成大部分工作，但我仍需要你审阅结果并提供建议，以持续优化输出质量。

感到压力太大？别担心！！🧘‍♂️ 与我交谈，我将引导你完成智能体编排。


## 环境要求

- Python 3.10+
- [Claude Code CLI](https://github.com/anthropics/claude-code)

## 安装

从源码安装：
```bash
# 克隆仓库
git clone https://github.com/Yancy456/Ralph-sequencer.git

python install.py
```

## 通过与 Ralph-sequencer Guider 对话来了解项目！

```bash
cd guider_demo # 进入一个空文件夹
ralph-sq template guide # 安装Guider模板
ralph-sq run # 指引员将带你了解整个项目
```

## 工作原理

Ralph-sequencer 使用项目下的配置文件 *ralph.yaml* 来编排多个智能体。

它按预定义的顺序运行 Claude Code CLI，提供了一种组织多个智能体的简便方法：

```text
       [ ralph.yaml ]
             |
             v
      [ Orchestrator ]
             |
             v
    /----------------\
    |   序列循环      | <-----------+
    \----------------/             |
             |                     |
             v                     |
    [ 步骤: 角色/提示词 ]           |
             |                     |
             v                     |
    [  Claude Code CLI  ]          |
             |                     |
             v                     |
    [  输出与统计数据   ] ---------+
             |
             v
         (( 完成 ))
```

核心执行过程使用以下命令：

```bash
claude --dangerously-skip-permissions --verbose --output-format stream-json -p "你的提示词文件"
```

## 开源协议

MIT
