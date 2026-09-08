# Java Code to ERD

从 Java 项目中的 ORM 映射、Mapper SQL、JDBC、DDL、Flyway 和 Liquibase 还原有证据支撑的数据库模型，并输出 Mermaid ERD、DBML 和 Markdown 报告。结果描述的是源码所表达的模型，不是线上数据库结构。

## 快速开始

安装后可直接请求“分析这个 Java 项目的数据库表关系并生成 ERD”。开发或调试时：

```bash
python3 java-code-to-erd/scripts/launch.py doctor --project /path/to/java-project
python3 java-code-to-erd/scripts/launch.py analyze --project /path/to/java-project
python3 java-code-to-erd/scripts/launch.py query --project /path/to/java-project --object sys_user
```

工具只静态读取项目源码和项目文件；不会连接数据库、执行 SQL、构建或运行项目、访问网络或安装软件。报告写入被分析项目的 `reports/java-code-to-erd/`，增量状态和人工复核记录写入 `data/java-code-to-erd/`。

完整工作流、证据规则和可视化验收要求见 [SKILL.md](SKILL.md)。
