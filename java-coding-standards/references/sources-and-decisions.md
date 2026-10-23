# 来源与融合决策

此文件用于溯源和冲突处理，不是每次编码必读。下列决策在项目明确规则缺省时生效；项目配置的实际范围先于本默认值。没有摘录的规则不声称已覆盖。

## 来源核验

1. 用户提供 `intellij-java-google-style.xml`，scheme 名为 GoogleStyle。SHA-256：`f25e4a8d94f2b2d33dd943cb672f570b64fb89e680df63d3795ad244505d0d26`。XML 解析核实了全局 option、Java 覆盖和其他语言节点；资产只保留全局 option 与 JAVA 节点，所有属性、子元素、顺序和值不变（序列化空白可变）。不把其他语言 2 空格/80 列继承给 Java。
2. 用户提供 `Java开发手册.pdf`，PDF 共 55 页。正文首页（PDF 第 4 页，印刷 p.1）版本表：**1.7.1，2022.02.03，黄山版**；附 1 版本历史 p.43 亦一致。SHA-256：`68463b8cc5f1ad8f9c4fcaaa7c468a46a7e603b23cd22f38414697782b404f1f`。文件创建日期 2022-05-11 不是手册版本日期。
3. 实际使用 Poppler 提取并逐段核对相关章节，渲染核对版本页。引用定位采用“章（节）条号”，页码为正文印刷页码。前言区分【强制】【推荐】【参考】，本 Skill 保留级别；说明/例子不升级为独立强制条款。
4. 提取限制：封面图像无文本；六（一）分层图不能仅凭文本还原箭头，二（一）及六（二）部分强调文字/内链提取为空。未据此编造丢失文字或复制图。精选规则均有可读正文依据；不是对整本手册所有图、附录错误码和部署建议的完整再版。原 PDF、完整提取文本及渲染图均不随 Skill 分发。

| 资料 | 主要原文定位 |
| --- | --- |
| 排版 | 一（三）p.4–6；XML 全局及 JAVA |
| [命名/结构](naming-and-structure.md) | 一（一）（二）1、4–6（四）1–5、13–18、26（八）（九）p.1–9、17–21 |
| [金额/数值/日期](numbers-and-dates.md) | 一（二）2–3（四）6–10、12（五）p.3、7–10 |
| 集合/泛型 | 一（六）p.10–14 |
| 并发 | 一（七）p.14–17 |
| 异常/日志 | 二（二）（三）p.25–28；六（一）2 p.37 |
| 资源/安全 | 二（二）6 p.25；四 p.31；六（三）1 p.39 |
| 数据库访问 | 五 p.32–36；四 3；一（四）11 |
| 测试 | 三 p.29–30 |

## 唯一执行结论

| ID | 来源差异/条件 | 执行结论及理由 |
| --- | --- | --- |
| D1 | XML 100 列 vs 一（三）8【强制】120 列 | 默认 100 列；续行两者均 +4。Java 4 空格覆盖全局 2；类头空行 1 覆盖全局 0。排版以用户 XML 为准 |
| D2 | XML 未声明所有空格/编码；工具名相似 | XML 明示项优先，其余用格式参考所列手册项；不推定 google-java-format 等价。不全局导入、不擅加构建插件 |
| D3 | 一（四）8【强制】金额最小单位整数；五（一）6【强制】小数 decimal | 新金额存储默认最小单位整数并明确币种/单位；其他精确小数用 decimal/BigDecimal。已有 DECIMAL 金额契约优先保持，运算用 BigDecimal 与显式舍入，不把 double 作为折中；不为 Skill 迁移数据 |
| D4 | POJO 包装/默认值/toString、作者日期要求 vs 非空模型/隐私/事实 | 默认按 POJO 条款；项目明确非空/record 模型优先。toString 仅安全字段；未知作者和创建日期不编造、可省略说明；普通修改不追问、不补全历史作者。这是本 Skill 的事实边界决策 |
| D5 | 一（六）12 的“super 不能 get”、16 的 raw 示例、18 的 values 是 list 等过度概括 | 按 Java API/JLS：super 能 get 为 Object；新代码菱形泛型；Map.values 返回 Collection，非必然 List；Arrays.asList 可 set；toArray 不保证某形式在所有 JDK 性能最优。保留原级别与定位，不复制错误解释 |
| D6 | 一（五）1 年份 y、4 禁 java.sql 时间类；旧驱动/现代日期 | 日历年不误用 YYYY；java.time 严格解析可用 uuuu（proleptic year），yyyy 是 year-of-era。Java 8+ 优先 java.time；旧 JDBC 驱动只支持 sql 时间类时允许在适配边界转换，不泄露到领域层，不谎称手册没有禁令。依据为实际驱动能力与 DateTimeFormatter API |
| D7 | 手册早于现代语法及虚拟线程全面落地 | 以编译目标和框架支持判断：Java 8 不用 var/record/List.of；var 10+，record 16+，标准 switch 表达式 14+，虚拟线程 21+。完整 enum/sealed 的穷尽 switch 不强添掩盖缺项的 default；传统非穷尽 switch 仍按手册。虚拟线程若项目明确采用，不机械改成平台 ThreadPoolExecutor；不池化虚拟线程，仍限制下游并发、超时及生命周期。依据 JLS switch/record 与 JEP 444，非手册新要求；不开 preview、不升级 Java |
| D8 | 二（二）3 细分异常、9【强制】Throwable 隔离 | 普通逻辑捕获可处理的具体类型；RPC/动态加载的故障隔离边界才考虑 Throwable，不能吞掉 VM 致命错误或返回伪成功。记录/转换保留 cause，边界外传播 |
| D9 | 日志占位符 vs 二（三）6【强制】级别判断 | 默认 trace/debug/info 仍显式判断；已有项目明确的惰性 API 等价执行时依其契约。占位符本身不能代替昂贵实参求值判断；不升级日志库 |
| D10 | 一（七）11说明中的重试次数/冲突率、12 的调度概括 | 保证更新原子性；重试取项目幂等和总时限预算，不强塞至少三次；ScheduledExecutorService 单周期任务异常可能阻止其后续执行，需错误处理。HashMap 并发不安全，不能把旧版本 resize 死链解释推广到所有 JDK |
| D11 | 五章 MySQL 工程约定 vs 项目数据库契约 | Java 数据访问精选按 database.md；不为本规范删外键/改逻辑删除/改表。MySQL 专属条款不推广到其他数据库；有 schema 变更任务才加载项目设计依据 |
| D12 | 一（十）2 外部列表空容器 vs 二（二）10【推荐】方法可 null | 前端列表无结果返回空容器；内部方法保持文档化可空契约；不把远程失败伪造成“成功的空结果” |

API 事实的核对入口：[Java 8 Collections/Arrays](https://docs.oracle.com/javase/8/docs/api/java/util/Arrays.html)、[Java 8 Map](https://docs.oracle.com/javase/8/docs/api/java/util/Map.html)、[Java 8 DateTimeFormatter](https://docs.oracle.com/javase/8/docs/api/java/time/format/DateTimeFormatter.html)、[Java 21 JLS](https://docs.oracle.com/javase/specs/jls/se21/html/index.html)、[JEP 444](https://openjdk.org/jeps/444)。这些是维护定位，不要求运行任务每次联网；本次以可执行 Java 示例核对选定 API 行为，不宣称逐链接在线验证。

## 检查能力边界

IDEA XML：排版和导入相关；项目已有 Checkstyle/PMD/SpotBugs 等：仅能自动检查其实际启用规则，未启用的适用规则仍需遵守；编译与测试：目标语法/API 和被覆盖行为。它们都不能证明业务正确、无数据竞争或无安全问题。业务命名、空值契约、资源所有权、事务边界、授权、最小改动和适用例外仍需 Agent/人判断。示例为自行编写，未复制手册大段内容。
