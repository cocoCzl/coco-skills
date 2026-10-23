# Java 编码规范轻量评测

`evals.json` 包含 27 个行为案例，`trigger-evals.json` 包含 32 个平衡近邻请求。结构检查只验证案例格式，不执行 Agent、不代表行为通过。运行方式沿用 [仓库评测说明](../README.md)，产物/调用记录只写临时目录，不提交报告。

新增的上下文案例将项目、目标文件、diff 或上轮契约直接放入现有 `prompt`/`query`，导出时不会丢失。包含未点名语言的取消接口、空值修复、提交审查、后续补测试，以及 Java 仓库仅改 Vue、README、工作流和前端 diff 的反例。格式通过不代表这些输入已由 Agent 执行。

## 普通 DTO 必要读取开销

比较对象是仅含 id、名称、布尔属性、无数值运算的普通 DTO，不含两版相同的项目配置及目标文件。必要文件仍为入口和命名资料，共 2 份；新金额/数值/日期资料不默认读取。

| 文件（UTF-8 字节） | 修改前 | 修改后 |
| --- | ---: | ---: |
| `SKILL.md` | 6,367 | 6,957 |
| `references/naming-and-structure.md` | 4,419 | 2,972 |
| 合计 | 10,786 | 9,929 |

净减少 857 字节（约 7.9%）；入口增加了逐项覆盖及上下文适用说明。这里只比较源码读取字节，不是实际 tokens、完整会话成本或触发率。金额/数值/日期规则、级别、适用条件及原示例迁入一份 `references/numbers-and-dates.md`，不是删除规则。

## 代表任务复现

为每个任务建立独立临时工程，将当前 Skill 完整复制到另一个临时目录。只给 Agent 真实任务、工程及可用 Skill 的 name/description/入口位置，不提供预期答案；不要预先强令它读取 Skill 来冒充隐式触发测试。工具权限、模型和输入保持一致。需要对照时在新会话使用相同工程且不提供此 Skill。

| 样本 | 工程与任务设置 | 检查实际结果 |
| --- | --- | --- |
| DTO / 风格覆盖 / 缺工具 | AGENTS 指定 Java 8、2 空格、120 列，无构建/检查工具；已有一个无关 Java 类。新增 UserDTO 的 Long id、String displayName、Boolean deleted 及访问器 | 实际选 Skill；只读入口和命名资料；使用项目缩进/版本；无无关修改、全量规范加载、安装工具或 getter 镜像测试 |
| 资源 / 并发 / 异常 | Java 8 方法：获取 ReentrantLock，设置 ThreadLocal，用拥有的 Reader 读首行，只在成功路径 close/remove/unlock；请求修复失败清理且保留 IOException | 读取对应资料；失败也关闭/清理/解锁，主异常与关闭异常关系正确；测试正常、空输入、读失败、关闭失败及同时失败 |
| 现代模型 | Java 21 record StatusView(State state)，State 为 READY/DONE；穷尽 switch 错把 DONE 返回为 Ready。仅修标签为 Done | 保留 record/穷尽 switch，无强添 default、Java 8 降级或构建升级；只改一行并验证相关行为 |
| 不适用近邻 | “解释 extends/super 和 Arrays.asList 不能 add 的原因，不审查或修改代码” | 不读完整 Skill，不扫描项目/构建；解释 super 可读 Object、asList 可 set |

这些是最小样本，不代替完整触发集。`java11`、`java25` 等行为案例还需各自独立执行；程序编译示例不证明这些 Agent 案例通过。没有对应模型/权限/工具时明确未验证，容量或执行错误不计成功。

以下为此前已记录的 4 个受控样本，非本轮重跑结果。四者都**没有显式调用 `$java-coding-standards`，也没有要求必须读取 Skill**；测试提示主动提供了可用 Skill 的描述及入口，由 Agent 自行决定：

| 样本 | 实际选择与验证结果 |
| --- | --- |
| DTO | 选择 Skill，只读入口及命名资料；遵守项目 2 空格，新增一个 DTO；JDK 21 以 `--release 8` 编译通过（不是 JDK 8 运行证据） |
| 资源修复 | 选择 Skill，读取资源、并发、异常和测试资料；验证正常、空输入、读取失败、关闭失败及同时失败的释放/清理/异常保留；JDK 21 编译 Java 8 目标并运行 |
| 现代模型 | 选择 Skill，读取入口、测试及版本资料；JDK 21 编译运行，验证 READY/DONE、record 访问器及 null 行为，仅修改一行，保留穷尽 switch |
| 概念解释 | 未选择 Skill、未读取文件或调用工具；正确解释 super 可读 Object、asList 可 set 但不可增删 |

另有一个未提供 Skill 的 DTO 对照样本也成功，不能据此宣称 Skill 提升了质量。上述结果属于描述/路径注入下的受控选择与执行证据，不是产品安装后的自然自动发现验证；没有完整触发率或可量化成本结论。显式调用成功只能证明加载后行为，不能作为自动触发成功的证据。

IDE 独立性复用已有 DTO 和资源修复样本：它们没有读取或导入 XML，也没有调用 IDEA/格式化器，直接按项目与 Skill 文字规则完成编码及自查，编译/行为验证使用已有 JDK。此证据不表示已验证任何 IDE 的格式化等价性；无需另建其他 IDE 配置或重复执行相同样本。

观察工具记录中的实际读取路径/字节、修改文件、命令、追问、运行环境及可取得的 usage；拿不到工具轨迹/usage 时明确缺项，不从字节估算 tokens。描述目录注入只是受控发现样本，不等于产品安装后自动发现测试。显式 `$java-coding-standards` 的执行只能验证加载后的行为。

## 本轮受控 Agent 样本

复用上面的临时工程与目录描述注入方式，使用本机既有 Codex 配置运行 3 个独立会话；仅提供可用 Skill 的 name/description/入口，不强令读取，不提供答案或评测断言。以下按工具轨迹和实际文件差异核对，不是完整触发集执行：

| 样本 | 实际读取的 Skill 资料 | 完成与范围 |
| --- | --- | --- |
| 普通 DTO，项目 2 空格/Java 8 | 入口、命名与结构；共 9,929 字节 | 选择 Skill；仅新增 DTO，按项目缩进；`--release 8` 编译和签名检查通过，未加载数值日期资料或新增 getter 测试 |
| “修复这里返回空值时报错的问题”，目标 OrderService.displayName | 入口、异常日志、测试 | 选择 Skill；先复现 NPE，后验证不存在订单返回约定文案、正常及 null 名称保留、仓库及取名异常原样传播；JDK 21 以 `--release 8` 编译运行，只改方法及新增回归测试 |
| Java 工程仅改 Order.vue 取消按钮 CSS | 无 | 未选择 Java Skill；仅改 CSS 的 blue 为 red，无后端或构建变更 |

三个样本均完成，项目快照对比未发现无关文件变更；临时 Skill 副本未改。DTO 的 Java 8 目标编译不是在 JDK 8 运行的证据。未执行取消接口、提交审查、后续补测试、README/工作流等全部新增案例；未做本轮无 Skill 对照，因此不声称质量提升或产品安装后自然触发率。原始运行记录留在临时目录，不提交仓库。

## 确定性验证

```bash
python3 scripts/check_all_skills.py
python3 -m unittest tests.java_coding_standards.test_package -v
python3 -m unittest tests.java_coding_standards.test_java_examples -v
python3 -m unittest tests.test_eval_contract -v
```

示例测试直接提取 reference 的 Java 代码块，编译并执行值相等、集合视图/PECS、锁失败释放、文件读取及现代语法示例；JDBC 片段只编译，日志片段依赖项目 SLF4J/异常类型、未在此独立执行。无外部数据库集成验证，无 IDEA 排版引擎逐项行为验证。

默认使用已安装且可运行、主版本匹配的 `javac/java`。可通过 `JAVA_TEST_HOMES`（操作系统路径分隔符分隔的多个 JDK home）加入现有 JDK，不下载或安装。记录实际 JDK 和编译目标：在 JDK 17 上 `--release 11` 编译并运行，不等于在 JDK 11 上运行。版本样本不是 Skill 的支持版本白名单；未来正式 JDK 仍按项目实际能力适配。

包装测试固定原 XML 的 Java 投影规范化指纹，不依赖本地原 PDF/XML；机器接口分类测试确认原有 Skill 和新未分类 Skill 缺 Schema 仍失败、指导型不能偷偷增加 scripts/schemas。测试不随 Skill 安装。

初次加入该 Skill 时有 7 个测试方法：`test_package.py` 的 5 个分别验证 Java 配置投影保真、安装包内容边界、既有接口 Skill 仍需 Schema、新未分类 Skill 不能缺失/提供无效 Schema、指导型不能新增未校验接口目录；`test_java_examples.py` 的 2 个验证通用 reference 示例及按版本标注的现代语法/API 示例。另把新 Skill 纳入现有评测结构测试，验证当时 19 个行为案例和 24 个平衡触发请求的格式，不执行这些案例。历史全量结果为 238 项、229 通过、9 项既有 PDF 环境跳过，不作为本轮全量运行结果。本轮另有 JDK 发现行为测试，验证匹配运行时可用、版本不匹配或运行失败时不计作可用 JDK。


## JDK 验证记录与 CI

从 Skill 使用 README 集中移入的历史代表性示例记录：

| 验证方式 | 实际版本与范围 |
| --- | --- |
| 对应 JDK 编译并实际运行 | 通用示例在 JDK 8、17、21、25 各自编译运行；版本示例另在 JDK 17 运行 record/switch、JDK 21 运行虚拟线程 |
| 交叉编译及较新运行时验证 | Java 11 示例以 `--release 11` 在 JDK 17、21、25 编译并运行；Java 17 示例另在 JDK 21、25 以 `--release 17` 编译运行；Java 21 示例另在 JDK 25 以 `--release 21` 编译运行 |
| 未验证 | 未在真实 JDK 11 运行；不覆盖所有 JDK、厂商或项目框架；JDBC 只编译、无数据库集成；日志片段未独立执行 |

本轮本地使用 JDK 21.0.9：通用示例以目标 21 编译并在 JDK 21 运行，Java 21 示例同版本编译运行；Java 11/17 示例以 `--release 11/17` 在 JDK 21 编译运行，属于交叉编译加较新运行时验证。未重跑历史全部 JDK 环境。

CI 新增独立 `java-examples` job，用 `actions/setup-java` 固定 Temurin JDK 21，核实 `javac/java` 主版本配对后执行实际示例测试。缺 JDK、编译/行为失败或任何示例跳过均使该 job 失败；本地缺 JDK 仍允许明确跳过。原 core 与 PDF job 保留。CI 固定 21 不表示 Skill 仅适用 Java 21，也未扩展 CI JDK 矩阵。

本轮结构/链接检查及 11 项相关单元测试全部通过、无跳过；未重复无关全量测试。本地解析过工作流，并在 JDK 21 执行其验证步骤（本机命令为 `python3`，CI setup-python 提供 `python`）；这不代表远端 CI 已运行通过。
