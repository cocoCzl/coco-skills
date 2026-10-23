# java-coding-standards

纯指导型 Skill，用于 Java 新增、修复、重构和代码审查。融合用户 IDEA XML 与《Java 开发手册》黄山版 1.7.1；遵守项目规范、Java 编译目标和既有工具。不是完整手册替代品，也不保证安装后每次自动触发或单靠 Skill 保证质量。

这是与 IDE 无关的通用 Java 规范 Skill：在 Codex CLI、VS Code、IDEA 或其他编码环境中，Agent 都直接执行适用的编码与格式文字规则，并按已有优先级处理项目规范。不需要安装 IDEA、导入 XML 或调用 IDEA 格式化器。

**依据目标项目 Java 版本选择规则、语法和 API**，不预设固定版本基线。以项目实际编译目标、运行环境及框架支持为准，不强迫旧项目升级，也不把新项目降为 Java 8 写法。示例标注的是该示例的最低版本，不代表所有 JDK 已验证；适用条件见 [Java 版本适配](references/java-versions.md)。

## 安装与调用

仓库根目录安装本地版本（发布后才可使用远程仓库版本）：

```bash
npx skills add . -g --agent codex --skill java-coding-standards
# 或仅复制该 Skill 目录到所用 Agent 的技能目录
cp -R java-coding-standards ~/.codex/skills/
```

显式调用：`使用 $java-coding-standards 修复 OrderService 的空指针问题，保持现有 API。`

也可直接说“给订单新增 DTO”“修复这个 Java 方法”“重构重复校验”“审查这段并发代码”。元数据允许隐式调用；实际发现和选择由 Agent 环境决定。纯 Java 概念、PDF 内容讨论不启动编码流程；仅生成 ERD 用 java-code-to-erd，仅提取简历事实用简历 Skill。

## 加载和来源

默认只读 [SKILL.md](SKILL.md)；普通 DTO 再读命名与结构。并发、异常日志、集合、资源安全、数据库、测试分别按需读取；默认排版细节或来源争议才读取格式/决策文件。不要求运行脚本、doctor、route、JSON 或生成报告。

缺省 Java 缩进/续行 4，右边界 100，类头后 1 空行；保留静态导入在前等 XML 实际配置。[格式文字规则](references/formatting.md) 已整理必要的全局设置和 Java 专属覆盖，普通编码按文字执行，不需要每次读取 XML。

java-code-style.xml 是可选的 IntelliJ IDEA 格式配置；Skill 本身与 IDE 无关，Agent 按 Markdown 中的通用 Java 规范执行。

[java-code-style.xml](assets/java-code-style.xml) 不是通用格式化配置，也不是 Skill 生效的前提。仅在确需配置 IDEA 且符合项目要求时使用，不自动改全局 IDE；不等同于 google-java-format。

[来源与冲突说明](references/sources-and-decisions.md) 记录来源指纹、章节、级别和融合决策。原手册及临时提取文件不分发。规则是精炼改写及原创示例，未再版手册；仓库 MIT 不代表对源手册取得再分发授权。

## 验证与限制

维护检查：在仓库根执行 `python3 scripts/check_all_skills.py` 及 `python3 -m unittest discover -s tests -p 'test_*.py'`。仓库 `evals/java_coding_standards/` 保存行为/触发案例；`tests/java_coding_standards/` 验证配置保真、包装边界和可执行示例，均不装进 Skill。详见该评测目录 README 的复现方式与证据边界。

本轮已有验证范围（仅限代表性示例）：

| 验证方式 | 实际版本与范围 |
| --- | --- |
| 对应 JDK 编译并实际运行 | 通用示例在 JDK 8、17、21、25 各自编译运行；版本示例另在 JDK 17 运行 record/switch、JDK 21 运行虚拟线程 |
| 交叉编译及较新运行时验证 | Java 11 示例以 `--release 11` 在 JDK 17、21、25 编译并运行；Java 17 示例还在 JDK 21、25 以 `--release 17` 编译运行；Java 21 示例还在 JDK 25 以 `--release 21` 编译运行 |
| 未验证 | 未在真实 JDK 11 运行；未覆盖所有 JDK、厂商或项目框架；JDBC 示例只编译，未做数据库集成；日志片段未独立执行 |

已有仓库全量测试 238 项：229 通过，9 项因既有 PDF 渲染环境条件跳过。新增测试及 4 个受控 Agent 样本的范围见仓库 `evals/java_coding_standards/README.md`；案例格式通过不代表 Agent 行为通过，受控发现样本也不证明安装后稳定触发。

本轮未验证真实 IDEA 格式引擎，不承诺完全复现其格式化结果。排版、静态规则、编译及测试复用项目已有工具。语义命名、业务契约、并发正确性、权限、资源所有权、重构范围依赖 Agent 判断与工程审查。没有格式化工具时仍按文字规范编写并限定范围人工自查，说明未自动验证项，不能声称自动检查通过。

## 可选项目 AGENTS.md

由项目维护者自行接入；本仓库不会修改其他项目：

```markdown
对本项目实际编写、修改、重构或审查 Java 代码时，使用已安装的
$java-coding-standards，先读取相关目录约定及实际编译目标。
遵循运行环境的指令层级；在不冲突时，本项目明确规范与生效工具配置
优先于 Skill 默认，Skill 仅补缺省项。
Skill 未安装或不可读取时明确说明，继续遵循项目规范，不自动安装
Skill、工具或依赖。
仅加载本次任务相关资料，最小范围修改，复用已有编译和检查任务。
纯概念解释、只生成 ERD 或只提取履历事实不启动完整编码规范流程。
工具不可用时说明检查范围和未验证项，不自行安装插件或升级 Java。
```
