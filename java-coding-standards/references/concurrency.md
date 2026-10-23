# 并发

来源：一（七）p.14–17。普通 DTO 不加载此文件。

- 【强制，1–4】单例及共享方法线程安全；线程命名有业务含义。默认平台线程复用现有受管执行器；新增自有池时显式配置 ThreadPoolExecutor 的线程数、有限队列、拒绝策略、命名工厂及生命周期。不随手用 Executors 固定/缓存池的无界默认，不每请求 new Thread。容量来自负载/资源约束，不能猜一个万能值。Java 21+ 虚拟线程另见 D7，不照搬池化思路。
- 【强制，5–6】不无保护共享 SimpleDateFormat；Java 8+ 可用不可变 DateTimeFormatter。自建 ThreadLocal 在 finally remove，明确谁拥有设置/清理；嵌套上下文若需恢复旧值按框架协议，不误删调用者上下文。
- 【强制，7–10】锁只覆盖必要临界区，避免持锁远程调用；多锁顺序一致。阻塞 lock 在 try 前，紧接 try/finally 解锁；tryLock 成功才进入/释放。不能在获取失败路径 unlock。
- 【强制，11】并发更新需原子操作/锁/版本条件避免丢更新。原说明推荐冲突概率低于 20% 用乐观锁且重试不少于 3 次；这是经验参数，不覆盖项目延迟、幂等、取消与重试预算（D10）。
- 【强制，12】多个定时任务避免 Timer 单任务异常终止整个调度线程，采用现有 ScheduledExecutorService。API 补充：周期任务抛异常仍可能停止它自己的后续执行，必须有可观测的失败策略。
- 【推荐，14、16】CountDownLatch 的 countDown 放在任务 finally；DCL 延迟初始化引用用 volatile。【参考，17、19】volatile 不使 count++ 原子，ThreadLocal 不保护其引用的共享对象。
- 【融合决策】遵守任务中断/取消，能抛 InterruptedException 则传播；必须转换时恢复中断标记并退出/上报，不能吞后继续。自有 executor 在拥有者生命周期结束时关闭，不关闭借入的受管池。这是 API 生命周期补充，不虚构为手册条目。

自行编写 Java 8+ 方法体，`lock` 是 ReentrantLock，`action` 是 Runnable：

```java
lock.lock();
try {
    action.run();
} finally {
    lock.unlock();
}
```

验证应覆盖异常释放/取消/拒绝等本次变更路径；一次并发测试成功不能证明无竞争。不要给普通单线程修改添加线程池或压力测试。
