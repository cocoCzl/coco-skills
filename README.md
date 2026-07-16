# Coco Skills

`coco-skills` 是一个面向 Codex / agent 工作流的开源 skill 合集仓库。带有 `SKILL.md` 的顶层目录是可独立安装和阅读的 skill；`tests/`、`examples/`、`evals/`、`scripts/` 等是仓库级开发资料。

当前包含：

| Skill | 用途 | 入口 |
|---|---|---|
| `football-betting-assistant` | 中文足球竞彩、赛前分析、胜平负、让球、比分、大小球、串关和赛后复盘辅助 | [`football-betting-assistant/SKILL.md`](football-betting-assistant/SKILL.md) |
| `lottery-number-recommendation` | 大乐透与双色球的完整历史校验、号码推荐和回测辅助 | [`lottery-number-recommendation/SKILL.md`](lottery-number-recommendation/SKILL.md) |

## 安装使用

把需要的 skill 目录复制或链接到你的 agent skills 目录中。例如：

```bash
cp -R football-betting-assistant ~/.codex/skills/
```

不同 agent 的 skills 目录可能不同；以你使用的 agent 文档为准。仓库里的顶层 skill 目录才是开源源码，`.agent/`、`.agents/`、`.claude/`、`.pi/` 等目录是本地运行态或安装态目录，不应该提交。开发或修复已有 skill 时，必须只修改顶层源码目录，例如 `football-betting-assistant/`，不要修改 `.agents/skills/...` 的本地安装副本。

## 仓库结构

推荐每个 skill 使用类似结构：

```text
skill-name/
  SKILL.md
  README.md
  references/
  schemas/
  scripts/
```

其中 `SKILL.md` 是 agent 触发和执行 skill 的主入口；`README.md` 面向人类使用者；`references/`、`schemas/`、`scripts/` 按需提供。运行时 skill 目录不放测试代码或样例数据。

仓库级测试统一放在：

```text
tests/
  skill_name/
    test_*.py
```

仓库级样例和 fixture 统一放在：

```text
examples/
  skill_name/
    *.json
tests/
  fixtures/
    skill_name/
      *.json
```

仓库级行为验收样例统一放在：

```text
evals/
  skill_name/
    evals.json
```

`tests/`、`examples/`、`evals/` 下的目录名使用 Python 友好的下划线形式，例如 `football_betting_assistant/` 对应 `football-betting-assistant`。测试入口、测试 fixture、样例数据和 eval 描述不要放进运行时 skill 目录。

## 开发检查

如需做仓库级开发检查，使用仓库根目录下的工具脚本，不把测试入口放进单个 skill 运行时目录：

```bash
python3 scripts/check_all_skills.py
python3 -m unittest discover -s tests -p 'test_*.py'
python3 football-betting-assistant/scripts/validate_inputs.py examples/football_betting_assistant/single-match-input.json
python3 football-betting-assistant/scripts/fetch_match_data.py --football --raw-input tests/fixtures/football_betting_assistant/raw/sporttery-football-sample.json --out /private/tmp/football-snapshots
```

## 贡献

欢迎添加新 skill 或改进已有 skill。提交前请确认：

- 不提交真实 API key、token、密码或私有数据。
- 不提交本地安装态目录，例如 `.agent/`、`.agents/`、`.claude/`、`.pi/`。
- 不提交 IDE、系统缓存或临时文件。
- 每个 skill 至少包含 `SKILL.md` 和面向使用者的 `README.md`。
- 有脚本、schema 或示例输入时，提供可运行的检查命令。

详细约定见 [`CONTRIBUTING.md`](CONTRIBUTING.md)。

## 许可

本仓库使用 [MIT License](LICENSE)。
