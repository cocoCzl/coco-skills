# DDL、Flyway 与 Liquibase 规则

项目内 DDL 是“项目声明结构”的最高等级来源，但仍不代表实际数据库。解析 CREATE/ALTER/DROP、字段、主键、唯一约束、外键、索引、默认值、可空性和生成方式。

Flyway 按版本语义顺序处理迁移；重复迁移只在顺序明确时应用。Liquibase 处理 XML/YAML/JSON/SQL changelog、include/includeAll、context 和 rollback 定义。前向分析不能应用 rollback。

后续删除或改名的对象不进入当前默认 ERD，但历史名称和证据保留。迁移冲突、include 循环、缺失文件、自定义 Java change、无法确定的 context 或两套迁移工具顺序不明时，记录未解析项并降级，绝不执行迁移。
