# JdbcTemplate、JDBC 与 Java SQL 规则

识别 JdbcTemplate、NamedParameterJdbcTemplate、Connection、Statement、PreparedStatement、ResultSet 及常见 query/update/execute 调用。

还原文字块、字符串常量和无歧义简单拼接。命名参数与位置参数只代表值，不能被解析为表或字段。ResultSet 明确读取的列可补充字段使用和 Java 类型线索。

跨方法值传递只有在来源唯一、调用目标明确、全部位于项目源码中时才产生 `CODE_INFERRED`，默认 MEDIUM。分支合流、循环、反射或外部边界会停止确认并记录原因。
