# java-coding-standards

为 Java 编写、修复、重构和审查提供统一的格式与质量规范，兼容项目已有约定，不依赖特定 IDE。适用于 DTO、服务、集合、异常、并发、资源和数据访问等实际编码任务；用户没点名语言，但项目与目标文件明确为 Java 时也适用。

## 安装与调用

远程安装：

```bash
npx skills add cocoCzl/coco-skills -g --agent codex --skill java-coding-standards
```

在仓库根目录安装本地版本：

```bash
npx skills add . -g --agent codex --skill java-coding-standards
# 或复制整个 Skill 目录
cp -R java-coding-standards ~/.codex/skills/
```

显式调用：`使用 $java-coding-standards 修复 OrderService 的空指针问题，保持现有 API。`

也可直接说“给订单新增 DTO”“修复这个方法”“重构重复校验”“审查这次提交”，由目标代码和会话上下文确定是否适用。安装不保证每次自动选择。纯概念或手册讨论、仅生成 ERD、仅提取简历事实不启动编码流程；Java 仓库中仅改前端或 README 也不适用。

## 项目规则与按需加载

遵循运行环境指令层级；在不冲突时，用户当前明确要求和目标目录的项目明确规范优先。项目规则只覆盖对应的 Skill 默认条目，其他适用规则继续执行。例如项目规定 2 空格缩进，不取消异常处理或资源释放要求；静态检查未启用某条规则，也不代表无需遵守。已有格式配置不免除其余适用规则，相邻代码只作补充证据，不照搬已有错误。

按项目实际编译目标、运行环境及框架能力选择语法和 API，不预设固定 JDK 基线，不主动升级或降级。缺省风格为缩进/续行 4 空格、100 列、类头后 1 空行；细节见 [格式文字规则](references/formatting.md)。[java-code-style.xml](assets/java-code-style.xml) 保留为可选的 IntelliJ IDEA 格式配置，不是 Skill 生效前提，也不等同于 google-java-format；不自动导入或修改全局设置。

从 [SKILL.md](SKILL.md) 开始，普通 DTO 再读 [命名与结构](references/naming-and-structure.md)。涉及金额、数值或日期字段及其计算、比较、转换时再读 [金额、数值与日期](references/numbers-and-dates.md)。集合、异常日志、并发、资源安全、数据库和测试按任务读取，不全量加载资料，不要求脚本或运行报告。

## 限制与来源

纯指导型 Skill，不能替代编译、测试、工程审查和领域判断。复用项目已有工具；工具不可用时按文字规则限定范围自查，说明未自动验证项，不自行安装工具或升级构建。示例最低版本仅限定该示例，未覆盖所有 JDK、厂商和框架；未验证真实 IDEA 格式引擎，不承诺完全复现其输出。JDBC 示例无数据库集成验证，日志片段依赖项目日志库及异常类型。

融合用户排版 XML 与《Java 开发手册》黄山版 1.7.1。[来源与融合决策](references/sources-and-decisions.md) 保留定位、原级别和适用条件。规则为精炼改写及原创示例；不分发原手册，仓库 MIT 不代表取得源手册再分发授权。

## 可选项目 AGENTS.md

项目维护者可自行接入：

```markdown
对本项目实际编写、修改、重构或审查 Java 代码时，使用已安装的
$java-coding-standards，先读取相关目录约定及实际编译目标。
遵循运行环境指令层级；在不冲突时，用户明确要求和项目明确规范优先。
项目规则只覆盖对应的 Skill 默认条目，其他适用规则继续执行；
项目缩进不取消异常处理或资源释放要求，静态检查未启用不代表免除规则。
已有格式配置不跳过整个 Skill；不照搬相邻代码中的错误。
Skill 不可读取时说明并继续遵循项目规范，不自动安装 Skill、工具或依赖。
仅加载任务相关资料，最小范围修改，复用已有编译和检查任务。
纯解释、仅 ERD/履历提取或仅改非 Java 文件不启动编码规范流程。
工具不可用时说明检查范围和未验证项，不自行安装插件或升级 Java。
```
