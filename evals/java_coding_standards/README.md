# Java 编码规范轻量评测

`evals.json` 包含 19 个行为案例，`trigger-evals.json` 包含 24 个平衡近邻请求。结构检查只验证案例格式，不执行 Agent、不代表行为通过。运行方式沿用 [仓库评测说明](../README.md)，产物/调用记录只写临时目录，不提交报告。

## 代表任务复现

为每个任务建立独立临时工程，将当前 Skill 完整复制到另一个临时目录。只给 Agent 真实任务、工程及可用 Skill 的 name/description/入口位置，不提供预期答案；不要预先强令它读取 Skill 来冒充隐式触发测试。工具权限、模型和输入保持一致。需要对照时在新会话使用相同工程且不提供此 Skill。

| 样本 | 工程与任务设置 | 检查实际结果 |
| --- | --- | --- |
| DTO / 风格覆盖 / 缺工具 | AGENTS 指定 Java 8、2 空格、120 列，无构建/检查工具；已有一个无关 Java 类。新增 UserDTO 的 Long id、String displayName、Boolean deleted 及访问器 | 实际选 Skill；只读入口和命名资料；使用项目缩进/版本；无无关修改、全量规范加载、安装工具或 getter 镜像测试 |
| 资源 / 并发 / 异常 | Java 8 方法：获取 ReentrantLock，设置 ThreadLocal，用拥有的 Reader 读首行，只在成功路径 close/remove/unlock；请求修复失败清理且保留 IOException | 读取对应资料；失败也关闭/清理/解锁，主异常与关闭异常关系正确；测试正常、空输入、读失败、关闭失败及同时失败 |
| 现代模型 | Java 21 record StatusView(State state)，State 为 READY/DONE；穷尽 switch 错把 DONE 返回为 Ready。仅修标签为 Done | 保留 record/穷尽 switch，无强添 default、Java 8 降级或构建升级；只改一行并验证相关行为 |
| 不适用近邻 | “解释 extends/super 和 Arrays.asList 不能 add 的原因，不审查或修改代码” | 不读完整 Skill，不扫描项目/构建；解释 super 可读 Object、asList 可 set |

这些是最小样本，不代替完整触发集。`java11`、`java25` 等行为案例还需各自独立执行；程序编译示例不证明这些 Agent 案例通过。没有对应模型/权限/工具时明确未验证，容量或执行错误不计成功。

本轮上述 4 个受控样本均已执行。四者都**没有显式调用 `$java-coding-standards`，也没有要求必须读取 Skill**；测试提示主动提供了可用 Skill 的描述及入口，由 Agent 自行决定：

| 样本 | 实际选择与验证结果 |
| --- | --- |
| DTO | 选择 Skill，只读入口及命名资料；遵守项目 2 空格，新增一个 DTO；JDK 21 以 `--release 8` 编译通过（不是 JDK 8 运行证据） |
| 资源修复 | 选择 Skill，读取资源、并发、异常和测试资料；验证正常、空输入、读取失败、关闭失败及同时失败的释放/清理/异常保留；JDK 21 编译 Java 8 目标并运行 |
| 现代模型 | 选择 Skill，读取入口、测试及版本资料；JDK 21 编译运行，验证 READY/DONE、record 访问器及 null 行为，仅修改一行，保留穷尽 switch |
| 概念解释 | 未选择 Skill、未读取文件或调用工具；正确解释 super 可读 Object、asList 可 set 但不可增删 |

另有一个未提供 Skill 的 DTO 对照样本也成功，不能据此宣称 Skill 提升了质量。上述结果属于描述/路径注入下的受控选择与执行证据，不是产品安装后的自然自动发现验证；没有完整触发率或可量化成本结论。显式调用成功只能证明加载后行为，不能作为自动触发成功的证据。

IDE 独立性复用已有 DTO 和资源修复样本：它们没有读取或导入 XML，也没有调用 IDEA/格式化器，直接按项目与 Skill 文字规则完成编码及自查，编译/行为验证使用已有 JDK。此证据不表示已验证任何 IDE 的格式化等价性；无需另建其他 IDE 配置或重复执行相同样本。

观察工具记录中的实际读取路径/字节、修改文件、命令、追问、运行环境及可取得的 usage；拿不到工具轨迹/usage 时明确缺项，不从字节估算 tokens。描述目录注入只是受控发现样本，不等于产品安装后自动发现测试。显式 `$java-coding-standards` 的执行只能验证加载后的行为。

## 确定性验证

```bash
python3 scripts/check_all_skills.py
python3 -m unittest tests.java_coding_standards.test_package -v
python3 -m unittest tests.java_coding_standards.test_java_examples -v
python3 -m unittest tests.test_eval_contract -v
```

示例测试直接提取 reference 的 Java 代码块，编译并执行值相等、集合视图/PECS、锁失败释放、文件读取及现代语法示例；JDBC 片段只编译，日志片段依赖项目 SLF4J/异常类型、未在此独立执行。无外部数据库集成验证，无 IDEA 排版引擎逐项行为验证。

默认使用已安装且可运行的 `javac/java`。可通过 `JAVA_TEST_HOMES`（操作系统路径分隔符分隔的多个 JDK home）加入现有 JDK，不下载或安装。记录实际 JDK 和编译目标：在 JDK 17 上 `--release 11` 编译并运行，不等于在 JDK 11 上运行。版本样本不是 Skill 的支持版本白名单；未来正式 JDK 仍按项目实际能力适配。

包装测试固定原 XML 的 Java 投影规范化指纹，不依赖本地原 PDF/XML；机器接口分类测试确认原有 Skill 和新未分类 Skill 缺 Schema 仍失败、指导型不能偷偷增加 scripts/schemas。测试不随 Skill 安装。

本轮新增测试共 7 个方法：`test_package.py` 的 5 个分别验证 Java 配置投影保真、安装包内容边界、既有接口 Skill 仍需 Schema、新未分类 Skill 不能缺失/提供无效 Schema、指导型不能新增未校验接口目录；`test_java_examples.py` 的 2 个验证通用 reference 示例及按版本标注的现代语法/API 示例。另把新 Skill 纳入现有评测结构测试，验证 19 个行为案例和 24 个平衡触发请求的格式，不执行这些案例。已有全量结果为 238 项、229 通过、9 项既有 PDF 环境跳过；收尾仅调整文档，不重复全套执行。
