package audit;
interface AuditMapper extends com.baomidou.mybatisplus.core.mapper.BaseMapper<AuditEvent> {
 @org.apache.ibatis.annotations.Select("SELECT a.id,a.user_id FROM audit_event a JOIN app_user u ON a.user_id=u.id") AuditEvent find(Long id);
}
