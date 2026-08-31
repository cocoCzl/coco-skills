# Java Code to ERD

`java-code-to-erd` 是一个只分析 Java 项目源码和项目文件的 Coding Agent Skill。它从 JPA/Hibernate、MyBatis/MyBatis-Plus、JdbcTemplate/JDBC、SQL、DDL、Flyway 和 Liquibase 中整理数据库对象及关系，生成可验证的核心模型、Mermaid ERD、DBML 和 Markdown 报告。

它不会连接数据库、运行或构建目标项目、执行 SQL、访问网络、扫描外部 JAR，也不会自动安装任何软件。输出是“代码推导数据库模型”，不是线上数据库结构。

## 环境

- Python 3.10+：完整确定性分析所需，只使用标准库。
- JDK：仅用于额外的 Java 源码语法复核；不会编译目标项目。JDK 缺失、版本不匹配或复核不可用会单独列为环境诊断，不会降低已经确认的数据库分析结果。
- Mermaid CLI：可选。已经存在时生成 SVG；不存在时只生成 `.mmd`，不会安装，也不会影响数据库分析状态。此时图形检查状态为 `SOURCE_ONLY`。

## 使用

把目录复制或链接到 Agent 的 skills 目录后，可以直接说：

- “使用 java-code-to-erd 分析这个 Java 项目的数据库表关系。”
- “分析订单模块涉及的表并生成 ERD。”
- “查询 sys_user 与其他表的关系，并列出冲突。”

开发调试命令：

```bash
python3 java-code-to-erd/scripts/launch.py doctor --project .
python3 java-code-to-erd/scripts/launch.py analyze --project /path/to/java-project
python3 java-code-to-erd/scripts/launch.py query --project /path/to/java-project --object sys_user
python3 java-code-to-erd/scripts/launch.py verify-visuals --project /path/to/java-project
```

`verify-visuals` 只能在 Agent 已经逐张查看所有生成的 SVG，确认没有截断、重叠、拥挤、标签或方向问题后执行。渲染成功本身不会被误标成视觉验收成功。

用户可见文件写入被分析项目的 `reports/java-code-to-erd/`；增量状态和人工复核写入 `data/java-code-to-erd/<project-id>/`。详细边界见 [SKILL.md](SKILL.md)。
