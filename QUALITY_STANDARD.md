# Skill Quality Standard

本仓库以可执行任务效果、证据边界和实际成本评价 Skill。来源：[Agent Skills 公开规范](https://agentskills.io/specification)。

## 格式、建议与仓库约定

- **公开格式要求**：Skill 目录至少有 `SKILL.md`，包含 YAML frontmatter 和 Markdown 正文；`name` 为 1～64 字符、小写字母/数字/单连字符、与父目录一致；`description` 为 1～1024 字符。提供 `compatibility` 时为 1～500 字符。
- **公开推荐实践**：渐进加载、主指令约少于 5000 tokens / 500 行、聚焦的按需资料、确定性操作交给脚本。它们不是正文格式的硬限制；行数少不等于实际执行轻量。
- **本仓库约定**：顶层独立源码、面向人的 README、500 行预算、机器接口型 Skill 的结果信封及 Schema、`reports/`/`data/` 命名空间、单元测试、行为案例至少 10 个且每例至少 3 项预期、平衡近邻触发集至少 20 个。这些不是公开规范要求。检查器是针对本仓库简明 frontmatter 的结构检查，不是通用 YAML/官方完整校验器。

## 指导型与机器接口型

默认所有 Skill 继续校验 `schemas/agent-result.schema.json` 及其原有结果信封字段；缺脚本或缺 Schema 不构成豁免。`scripts/check_all_skills.py` 的显式 `INSTRUCTION_ONLY_SKILLS` 当前仅登记 `java-coding-standards`：它提供指令、参考资料与配置资产，不提供机器接口，不制造 scripts、Schema、doctor/route、JSON 或运行报告。登记项出现 scripts/schemas 目录即检查失败，须评审重新分类。

两类都须通过元数据、README、链接、包装边界及同样的评测结构检查。接口型继续运行现有脚本测试/性能检查；指导型验证来源、资产保真和代表性示例，行为另由真实 Agent 评测。新豁免必须明确评审分类及回归测试，不得为逃避接口校验改名登记。

## 质量与成本

| 特性 | 要求与证据 |
| --- | --- |
| 可发现 | 描述给出能力、触发和相邻不适用任务；通过真实近邻触发评测验证 |
| 正确可信 | 用户明确意图与已有上下文优先；脚本校验参数/格式/事实；区分证据、推断、未知 |
| 有边界 | 复用有效授权，保留个人贡献、保密与失败降级；不猜来源、不扩大权限 |
| 可执行 | 模式有可执行下一步或明确限制；必需依赖、错误和恢复状态可检查 |
| 轻量 | 按任务阶段读资料；明确操作直接执行，help/doctor/route 按需；避免重复审计/同步，不省略必要校验 |
| 可维护 | 规则有明确维护入口；领域流程保持各自特点，生成物与运行日志不进入源码 |

评估实际读取文件和字节、工具/重复命令、网络页数、扫描/计算/磁盘写入，以及追问/确认次数；能取得实际 tokens 时记录，不能取得时标注不可用，不把字节换算成实测 tokens。

## 三类验证必须分开报告

| 层次 | 能证明什么 | 不能证明什么 |
| --- | --- | --- |
| 结构检查 | 文件、链接、元数据约束、Schema/评测 JSON 结构符合仓库约定 | Agent 会触发、遵守规则、完成任务或达到发布要求 |
| 脚本行为测试 | 确定性路径、失败状态、数据/模型一致性及相关离线成本 | 真实 Agent 的选资料、意图判断、追问和交付质量 |
| 真实 Agent 评测 | 指定版本、输入、环境下实际执行结果和成本 | 未运行案例、其他模型/环境的普遍效果 |

新增/变更行为时补少量高价值案例，覆盖正常任务、近邻不触发、否定、已有上下文、缺依赖和恢复。案例 JSON 校验不是案例执行。真实评测保留执行方式、产物与调用记录，结果存临时目录；单例结果不可宣称全套通过。执行方式见 [evals/README.md](evals/README.md)。

## 本地检查

```bash
python3 scripts/check_all_skills.py
python3 scripts/benchmark_skill_entrypoints.py
python3 -m unittest discover -s tests -p 'test_*.py'
# 改动 Java 扫描/缓存时，比较旧快照与当前版本，避免并发污染计时
python3 scripts/benchmark_java_incremental.py --skill-dir /path/to/baseline/java-code-to-erd
python3 scripts/benchmark_java_incremental.py
```

使用 Python 3.10+。Java 基准在临时目录生成 600 文件、20 个有关联实体，测冷扫、重复和单文件修改；记录耗时、解析数、源码读取与状态写入，并比较事实哈希。隔离可选 JDK/SVG，不能外推为全部项目或渲染耗时。正式分析仍保留可选复核能力。

发布评审另确认：描述精度、无不必要加载/确认、降级准确、示例无私密数据；分别报告通过、跳过和未验证，不把自动检查替代 Agent 页面视觉检查或用户审阅。
