---
name: java-coding-standards
description: 在新增、修复、修改、重构或审查 Java 代码时使用，包含 DTO、服务、集合、异常、并发、资源与数据访问；用户未点名语言但项目及目标文件明确为 Java 时也适用，无需点名规范。融合用户排版配置与阿里巴巴 Java 开发手册黄山版，提供与 IDE 无关的文字规则，按任务加载并尊重项目 Java 版本、风格和工具链。仅改前端、README 等非 Java 文件时不因仓库含 Java 而启动；纯概念解释、PDF/手册讨论、仅生成 ERD、仅提取简历事实不启动编码规范流程。
---

# Java 编码规范

用于实际代码实现、局部格式调整及代码审查，依据目标项目 Java 版本选择规则、语法和 API，不预设固定版本基线。示例的最低版本仅限定示例 API，不代表所有 JDK 已验证；验证限制见 [README](README.md#限制与来源)。仅分析关系生成 ERD 由 `java-code-to-erd` 负责，仅提取履历由简历 Skill 负责；任务同时要求改 Java 时，仅对改动部分应用本 Skill。纯解释不启动检查、构建或重构流程。

这是适用于各类 Java 编码环境的通用规范 Skill。在 Codex CLI、VS Code、IDEA 或其他环境应用时，均按下述优先级执行适用的文字规则；不依赖安装 IDEA、读取/导入 XML 或调用 IDEA 格式化器。

## 优先级

遵循运行环境指令层级。在不冲突时，用户当前明确要求、目标目录项目明确规范优先；项目明确规则只覆盖对应的 Skill 默认条目，其他适用规则继续执行。例如项目缩进覆盖默认缩进，不取消异常处理或资源释放要求。生效的格式化、静态检查、构建配置决定执行方式；检查未启用某条规则不代表无需遵守。有格式配置也要应用其余适用条目。相邻代码只是补充证据，不复制已有错误。

配置不一致先查模块、目录、profile、source set 和 CI 生效范围；只有仍无法解决且影响任务的冲突才询问。不要改全局 IDE 设置、擅加插件或升级 Java。

下文【强制】【推荐】【参考】是手册原级别；推荐项可说明权衡，参考项按场景选择，不升级为硬门禁。【融合决策】是本 Skill 对冲突或 API 条件的执行结论，不冒充手册原文。

## 编写前

1. 确认任务是实现、修复、重构、格式化还是只读审查，圈定文件及必要调用方。
2. 读取目标路径适用的项目指令，按需看父/模块 POM、Gradle 构建与 toolchain、编译 release/source/target、已有检查配置和 CI 命令。运行 JDK 不等于编译目标；不要无差别全仓扫描。版本不明先沿用现有可确认语法，不擅用新 API；会影响实现时再澄清。
3. 仅加载下面与任务相关的资料；普通 DTO 默认只需本入口和命名与结构，涉及金额、数值或日期字段及其计算、比较、转换时再读相应资料；缺省排版要处理细节时才读格式资料。不要读完整手册或全部 references。

## 编写中

- 最小必要修改；不顺带全仓格式化、重命名或重构。审查请求默认只报告有位置、影响和建议的问题。
- 缺省排版：4 空格缩进、续行 +4、100 列边界、非空控制块加大括号；Java 类头后 1 空行。细节按 [格式文字规则](references/formatting.md) 执行，不必读取 XML；不要按 GoogleStyle 名称套标准 Google Java Style。
- 【强制】类 UpperCamelCase（DTO 等缩写例外）、成员/方法 lowerCamelCase、常量 UPPER_SNAKE_CASE；覆盖方法加 `@Override`（一（一）4–6、一（四）2）。
- 【强制】包装整数的值比较用空值安全的 equals；拆箱前确认非 null，不靠捕获 NPE 做条件判断（一（四）6–7、二（二）1）。
- 【强制】异常不能吞掉、`finally` 不 return；拥有的资源在异常路径也要释放（二（二）4、6–7）。
- 【强制】外部输入校验与权限校验不能缺失；SQL 值参数绑定，不能拼接用户输入（四 1、3–4）。不要将内部已验证参数机械地每层重复校验（一（八）13–14【参考】）。
- 保持 API、序列化和数据语义兼容；规则例外要有项目要求或实际 API 条件依据。不要为“通过”删测试、关闭规则或压制告警。

## 完成后

1. 自查 diff、新增/修改代码及必要关联位置，确认行为、边界、异常路径和改动范围。
2. 复用项目现有格式化、静态检查、编译与相关测试。先查任务命令是否会全仓写入；用已有检查模式/文件范围，不能限定时人工检查本次 diff。不把 google-java-format 当作此 IDEA XML 的等价实现。
3. 纯格式调整核对 diff 与可用格式检查即可，遵守项目必需检查；行为修改选择相关编译/测试，缺回归保障的核心行为补有价值测试。无新失败、改动或风险，不反复全量构建；不为简单 DTO/getter 机械生成测试。
4. 缺工具时仍按适用的文字规范编写并按范围人工自查，说明哪些未自动验证；不擅自安装或修改构建。简要交代改动、执行过的检查及限制，不要求 JSON、doctor、route 或运行报告。

## 按需资料

| 任务涉及 | 读取 |
| --- | --- |
| 默认排版细节、Java 导入声明或工具差异 | [formatting.md](references/formatting.md)；仅需配置 IDEA 时选用 [IDEA XML 资产](assets/java-code-style.xml) |
| 新类/DTO、命名、接口、注释、序列化 | [naming-and-structure.md](references/naming-and-structure.md) |
| 金额、数值、日期字段及其比较、计算、转换 | [numbers-and-dates.md](references/numbers-and-dates.md) |
| 集合、泛型、流、比较器 | [collections.md](references/collections.md) |
| 异常处理、日志、错误边界 | [exceptions-and-logging.md](references/exceptions-and-logging.md) |
| 共享状态、锁、线程池、ThreadLocal、异步 | [concurrency.md](references/concurrency.md) |
| 文件/连接/流生命周期、外部输入、权限、远程调用 | [resources-and-security.md](references/resources-and-security.md) |
| JDBC、ORM、SQL、事务 | [database.md](references/database.md)，拥有资源时加资源资料，修改异常处理时加异常资料 |
| 编写/修改测试，或行为变化需设计回归 | [testing.md](references/testing.md) |
| 新语法/API、编译/运行 JDK 不同、版本兼容判断 | [java-versions.md](references/java-versions.md) |
| 来源追溯、规则冲突、record/switch/虚拟线程等版本条件 | [sources-and-decisions.md](references/sources-and-decisions.md)，只看相关条目 |

安装可增加被发现的机会，不保证每次触发；未验证真实 IDEA 格式引擎，不承诺完全复现其格式化结果。Skill 不能代替编译、测试、工程审查和领域判断。
