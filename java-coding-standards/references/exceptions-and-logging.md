# 异常与日志

来源：二（二）p.25–26、二（三）p.26–28；分层边界参考六（一）2。

- 【强制，异常 1–4、8】可预检查的 NPE/越界不靠 catch 控制流程；数字解析的 NumberFormatException 等不可完全预检场景可捕获。缩小 try 范围、捕获可处理的具体类型；处理、转换且保留 cause，或上抛，不能空 catch。
- 【强制，异常 5–7】事务内 catch 后检查是否仍需回滚；资源异常路径也关闭，Java 7+ 可 try-with-resources；finally 不 return。不要只日志后返回成功/默认零而隐藏失败。
- 【强制原条目，异常 9】RPC、二方包、动态生成类调用的 Throwable 拦截用于隔离边界；不是每个业务方法 catch(Throwable) 的理由。只有负责故障隔离的边界采用，保留上下文，致命 VM 错误不伪装成可恢复成功；依据见 D8。
- 【推荐，异常 10–12】明确 null 返回条件，留意拆箱/远程返回值；优先有业务含义的异常，区分 checked 与 unchecked。【参考，异常 13】沿用项目错误码/Result 约定，不统一强塞包装返回值。前后端列表空结果按一（十）2【强制】返回空容器，内部可空契约不因此全局改变。
- 【强制，日志 1、5–6】复用项目日志门面，不新装实现；参数用占位符。默认 trace/debug/info 加级别判断，尤其在参数有计算开销时；项目明确采用等价延迟求值 API 时按该 API（融合决策 D9）。占位符不能避免方法实参被提前执行。
- 【强制，日志 8–10】生产服务不使用 System.out/err、printStackTrace；在负责处理的边界记录必要上下文及异常对象，不仅 getMessage；不要直接 JSON 序列化整个对象打日志。
- 【强制，日志 7】避免重复日志。只在确需修改日志配置时核对 additivity 和 appender 路由，不机械给所有 logger 加 false 导致日志丢失。【推荐，日志 11–14】控制量与级别，用户敏感日志脱敏；禁止展示明文敏感数据另来自四 2【强制】。不全量输出 DTO/toString。

日志保存天数/路径（二（三）2–4）属于部署和合规配置，不因一次代码修改改部署目录；需要修改时结合现行要求确认。手册历史期限不能冒充当前法律意见。

自写片段，Java 8+，项目已有 SLF4J 1.7+；`orderId` 为允许记录的标识：

```java
// 在负责最终处理的边界，避免每一层都重复记录后再抛出。
logger.error("Order load failed, orderId={}", orderId, failure);
// 转换异常时保留原始 cause；不要仅传 failure.getMessage()。
throw new OrderLoadException("Unable to load order", failure);
```

上面是两个不同职责的替代片段，不要求同一层同时记录和抛出。
