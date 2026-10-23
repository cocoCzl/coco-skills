# 金额、数值与日期

涉及金额/数值/日期字段、比较、计算或转换时读取；仅有普通标识和名称属性、无相关操作的 DTO 无需读取。定位均为黄山版章节及条号，按任务适用，项目明确契约逐项优先。

- 【强制】long 后缀 L，浮点后缀 D/F（一（二）2–3）。
- 【强制】包装数值比较用 `equals`/`Objects.equals`（后者 Java 7+）；不能用 `==` 依赖缓存。BigDecimal 数值等值用 `compareTo(...) == 0`，构造用十进制字符串或 `valueOf`，不能 `new BigDecimal(double)`；浮点近似等值需业务误差定义（一（四）6–7、9–10、12）。比例/金额舍入规则由业务确定。
- 【强制】手册金额存储以最小货币单位整数表示（一（四）8）；明确单位与范围，运算检查溢出。已有 DECIMAL/BigDecimal 契约按项目保持，不擅改数据模型；数据库小数条款的决策见来源文档 D3。
- 【强制】日历年不用周序年 `YYYY`，区分月份 M/分钟 m、24 小时 H/12 小时 h；不能把一年写死 365 天（一（五）1–2、5）。Java 8+ 可用不可变 java.time（手册一（七）5说明），明确时区；时间差用单调时钟，日期用业务时钟（API 补充）。旧 JDBC 类型及 `uuuu` 见 D6。

来源冲突及 API 条件见 [来源与融合决策](sources-and-decisions.md) D3、D6；仅需处理相关条件时读取。

自行编写的 Java 8+ 片段（不是完整类；无需因这些片段创建新测试）：

```java
// 反例：依赖 Integer 对象身份；金额被 double 先行舍入。
// boolean same = firstId == secondId;
// BigDecimal price = new BigDecimal(0.1D);

boolean same = Objects.equals(firstId, secondId);
BigDecimal price = new BigDecimal("0.10");
boolean equalValue = price.compareTo(new BigDecimal("0.1")) == 0;
```
