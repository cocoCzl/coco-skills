# Coco Skills

[English](README.en.md)

面向 Codex 与其他 AI Agent 的开源 Skill 合集。每个顶层 Skill 都包含可被 Agent 读取的 `SKILL.md`，以及供人快速了解和安装的精简 README。

## 收录的 Skills

| Skill | 说明 | 文档 |
|---|---|---|
| `ai-resume-expert` | 面向中国大陆技术岗位的、证据优先的简历生成、诊断、JD 定制与本地 PDF 交付 | [README](ai-resume-expert/README.md) · [SKILL.md](ai-resume-expert/SKILL.md) |
| `football-betting-assistant` | 中文足球竞彩赛前分析、组合建议、赛后复盘与回测辅助 | [README](football-betting-assistant/README.md) · [SKILL.md](football-betting-assistant/SKILL.md) |
| `java-code-to-erd` | 从 Java 源码、ORM 映射和 SQL 还原可验证的数据库模型与 ERD | [README](java-code-to-erd/README.md) · [SKILL.md](java-code-to-erd/SKILL.md) |
| `lottery-number-recommendation` | 大乐透和双色球的官方历史校验、号码生成与回测辅助 | [README](lottery-number-recommendation/README.md) · [SKILL.md](lottery-number-recommendation/SKILL.md) |

## 安装

使用 [skills.sh](https://skills.sh/) 安装指定 Skill：

```bash
npx skills add cocoCzl/coco-skills -g --agent codex --skill football-betting-assistant
```

本地开发时，在仓库根目录执行：

```bash
# 查看可安装的 Skill
npx skills add . --list --full-depth

# 安装本地源码中的指定 Skill
npx skills add . -g --agent codex --skill football-betting-assistant
```

也可以直接复制所需目录；以 Codex 为例：

```bash
cp -R football-betting-assistant ~/.codex/skills/
```

去掉 `-g` 可做项目级安装。不同 Agent 的安装位置有所不同，请以其文档为准。只安装顶层 Skill 源码目录；不要提交或修改 `.agents/`、`.claude/`、`.pi/` 等本地运行态目录。

## 使用方式

安装后直接用自然语言提出对应任务即可。Agent 会根据 `SKILL.md` 的触发条件、流程和安全边界执行；具体示例见各 Skill README 与 [`examples/`](examples/)。

各 Skill 的用户报告写入当前工作目录的 `reports/<skill-name>/`；运行数据若有保存需求，则位于该 Skill 声明的 `data/` 命名空间中。生成物不会写入安装目录。

## 开发

仓库级开发环境需要 Python 3.10+。提交前可运行：

```bash
python3 scripts/check_all_skills.py
python3 -m unittest discover -s tests -p 'test_*.py'
```

建议的目录约定：

```text
skill-name/                 # 可安装的 Skill 源码
  SKILL.md                  # Agent 主入口
  README.md                 # 面向使用者的简介
  references/ schemas/ scripts/
examples/                   # 可运行示例
tests/                      # 仓库级测试与 fixtures
evals/                      # 行为验收样例
```

质量要求见 [QUALITY_STANDARD.md](QUALITY_STANDARD.md)，贡献方式见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## License

[MIT](LICENSE)
