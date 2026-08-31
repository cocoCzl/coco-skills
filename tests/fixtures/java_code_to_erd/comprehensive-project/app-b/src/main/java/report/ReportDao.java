package report;
class ReportDao {
 void read(java.sql.Connection connection) throws Exception {
  String sql="SELECT id,user_id FROM report_job";
  java.sql.ResultSet result=connection.prepareStatement(sql).executeQuery();
  result.getLong("user_id");
 }
 String dynamic="SELECT id FROM report_${tenantId}";
}
