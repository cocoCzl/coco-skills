# 默认排版与配置

只在项目没有更具体规则时使用。资产由用户 XML 提取：保留所有根级 `option` 和 `codeStyleSettings language="JAVA"` 原值，仅移除其他语言节点。`GoogleStyle` 只是原 scheme 名称，不代表官方 Google Java Style。

下表右栏是与 IDE 无关、可直接执行的 Java 排版规则；左栏仅用于追溯配置依据。普通编码读取文字即可，不需要读取 XML、安装 IDEA 或运行其格式化器。XML 只是可选的 IDEA 配置资产。

| 实际位置/配置 | Java 的执行结论 |
| --- | --- |
| 根 `OTHER_INDENT_OPTIONS` 为 2/4/2；Java `indentOptions` 为 4/4/4 | Java 缩进 4、续行 4、Tab 宽度 4；全局 `USE_TAB_CHARACTER=false`，使用空格 |
| 根 `RIGHT_MARGIN=100`；Java 无覆盖 | 100 列默认边界；不使用手册 120 列或其他语言的 80 列 |
| 根 `BLANK_LINES_AFTER_CLASS_HEADER=0`，Java 为 1 | 类头后 1 空行 |
| 根/Java `KEEP_BLANK_LINES_IN_CODE=1`，根 `KEEP_BLANK_LINES_BEFORE_RBRACE=0` | 代码中最多保留 1 空行；右花括号前不保留空行 |
| `KEEP_CONTROL_STATEMENT_IN_ONE_LINE=false`；IF/DOWHILE/WHILE/FOR `BRACE_FORCE=3` | 控制语句不用单行省略块，大括号始终保留 |
| 参数、for 对齐 false；Java resources 对齐 false | 多行不按首参数/首资源纵向对齐，使用续行缩进 |
| call/method parameters、extends、throws keyword、chain、binary、ternary、for、array 的 `WRAP=1` | 必要时换行以遵守边界；不是每项强制单独成行。这是原配置的 wrap-as-needed 含义 |
| binary/ternary sign on next line=true | 折行时运算符放下一行；链调用的点随下行（一（三）8） |
| `WRAP_COMMENTS=true` | 注释可换行；不能切坏 URL、协议字符串或文本块内容 |
| `SPACE_BEFORE_ARRAY_INITIALIZER_LBRACE=true` | 数组初始化左花括号前留空格 |
| `INSERT_INNER_CLASS_IMPORTS=true` | 允许直接导入内部类 |
| 两类 import-on-demand 阈值 999，包白名单空 | 正常规模用显式导入；阈值不是绝对禁止星号，不能称为永远不折叠 |
| `IMPORT_LAYOUT_TABLE` | 静态导入组在前，空行，普通导入组在后；组内顺序遵循项目规则或现有工具，缺省保留局部一致顺序。XML 未显式声明字母排序，不要求运行 IDEA Optimize Imports |
| `JD_ALIGN_PARAM_COMMENTS`、`JD_ALIGN_EXCEPTION_COMMENTS=false` | Javadoc 参数/异常说明不做纵向填空对齐 |
| `JD_P_AT_EMPTY_LINES=false`；三种 `JD_KEEP_EMPTY_*=false` | 不因空行自动加 p；不保留空的 param/exception/return 标签 |
| `PARENT_SETTINGS_INSTALLED=true` | IDEA 配置继承标记，不是独立排版规则 |

其他全局缩进项（smart tabs、label、relative indents）也原样保留。Android XML、JS、Python、TypeScript、XML、CSS、HTML、JSON、PROTO/protobuf、SASS/SCSS、Objective-C 及其扩展均不属于 Java 覆盖，不进入提取资产。

XML 没有穷举 IDE 的全部默认值，不宣称跨 IDEA 版本完全一致。未声明的空格/括号细节补用一（三）1–4、6–7、9–10【强制】：非空块左括号同行，else 接右括号；关键字和括号间、二/三目运算符两侧、逗号后留空格，括号内不加空格；强转写 `(int)value`；`//` 后一空格；新文件 UTF-8/LF。不修改全局 IDE 编码或全仓换行。

【推荐】方法总行数控制在 80 行以内（一（三）11），不为凑行数拆碎逻辑；语义段落一空行，不填空格对齐赋值（一（三）12–13）。

没有格式化工具时，直接按上述文字编写并人工检查本次 diff 的缩进、续行、边界、空行、括号、导入分组和注释，说明未自动验证。项目已有格式化工具时复用其实际生效规则与检查范围；Spotless/google-java-format 等不因名称或配置相似就与本默认规则等价。

如选择使用 IDEA，格式化与 Optimize Imports 是不同动作；XML 本身不执行检查，也不检查命名、空值、线程安全、授权或 SQL 注入。人工检查、项目工具自动验证、IDEA 实际格式化结果须分别说明，未经验证不宣称结果完全一致。
