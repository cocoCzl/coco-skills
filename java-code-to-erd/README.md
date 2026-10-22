# Java Code to ERD

从 Java 项目中的 ORM 映射、Mapper SQL、JDBC、DDL、Flyway 和 Liquibase 还原有证据支撑的数据库模型，并输出 Mermaid ERD、DBML 和 Markdown 报告。结果描述的是源码所表达的模型，不是线上数据库结构。

## 快速开始

安装后可直接请求“分析这个 Java 项目的数据库表关系并生成 ERD”。开发或调试时：

```bash
python3 java-code-to-erd/scripts/launch.py analyze --project /path/to/java-project
python3 java-code-to-erd/scripts/launch.py query --project /path/to/java-project --object sys_user
```

工具只静态读取项目源码和项目文件；不会连接数据库、执行 SQL、构建或运行项目、访问网络或安装软件。报告写入被分析项目的 `reports/java-code-to-erd/`，增量状态和人工复核记录写入 `data/java-code-to-erd/`。

完整工作流、证据规则和可视化验收要求见 [SKILL.md](SKILL.md)。

明确任务直接 `analyze`，环境出错时再 `doctor`。保持全仓发现；重复分析复用哈希匹配片段，单次运行共享源码读取，缓存采用批量/定时原子检查点。可用 `python3 scripts/benchmark_java_incremental.py` 在临时 600 文件项目上测冷扫、重复和单文件修改；该基准隔离可选 JDK/SVG，不能代表渲染耗时。

发布中可处理的异常会回滚已覆盖的报告文件；最后更新 manifest。源码读取快照在单次分析退出（含异常）时解除引用，不跨任务驻留；不保证强制终止或持续存储故障下的跨文件事务。
