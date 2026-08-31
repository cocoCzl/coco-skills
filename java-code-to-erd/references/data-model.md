# 核心数据模型

`database-model.json` 是唯一权威来源，其他文件只能由它生成。

主要区域：

- `scope`：本次请求范围。
- `applications`、`profiles`、`dataSources`、`dialects`：身份和运行条件线索。
- `coverage`：发现、分析、跳过和未解析数量。
- `databaseObjects`：表、视图等持久对象及字段、键、约束。
- `codeObjects`：Entity、Mapper、Repository、DAO、查询结果类。
- `objectMappings`：Java 对象和数据库对象的多对多角色映射。
- `operations`：读取、插入、更新、删除等访问。
- `relationships`：有代码或声明证据的正常、条件或冲突关系。
- `candidates`：低可信命名候选；默认不进入 ERD 或 DBML Ref。
- `evidence`：仅相对路径、起止行和来源类别，不含源码片段。
- `conflicts`、`unresolved`：不能被可靠合并或解析的内容。

对象和字段 ID 来自稳定身份，不使用扫描顺序或运行时间。Java 类型和数据库类型分开保存；没有数据库类型证据时使用 `null`，不要从 Java 类型强行换算。

关系 `from` 表示保存引用字段的一端，`to` 表示被引用键的一端。SQL 的左右书写顺序不能决定方向。约束数量关系和代码数量关系分别放在 `constraintCardinality` 与 `codeCardinality`。
