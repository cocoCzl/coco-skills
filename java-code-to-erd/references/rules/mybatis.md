# MyBatis 与 MyBatis-Plus 规则

分析 Mapper Java/XML、四种 SQL 注解、Provider、SQL 片段/include、动态标签、`resultMap`、association 和 collection。

SQL 本身走通用 SQL规则。动态分支中的事实标记 `CONDITIONAL`。运行时集合值是参数，不是表或字段。无法解析的 Provider 或 Dynamic SQL 进入未解析项。

结果组织使用 `RESULT_MAPPING`，只说明查询结果结构，不能证明物理外键或数据库唯一性。DTO/VO 仍是查询结果对象。

MyBatis-Plus 的 `TableName`、`TableId`、`TableField` 建立实体映射；BaseMapper 泛型建立 Mapper 角色。Wrapper 的 lambda 字段只有能够映射到明确实体时才作为字段使用证据。
