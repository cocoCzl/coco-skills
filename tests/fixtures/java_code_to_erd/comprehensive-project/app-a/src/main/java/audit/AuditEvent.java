package audit;
@com.baomidou.mybatisplus.annotation.TableName("audit_event")
class AuditEvent {
 @com.baomidou.mybatisplus.annotation.TableId private Long id;
 @com.baomidou.mybatisplus.annotation.TableLogic private Integer deleted;
}
