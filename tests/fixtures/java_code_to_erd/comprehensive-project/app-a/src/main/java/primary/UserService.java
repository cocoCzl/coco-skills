package primary;
class UserService {
 private final org.springframework.jdbc.core.JdbcTemplate jdbc;
 private final UserRepository users;
 UserService(org.springframework.jdbc.core.JdbcTemplate jdbc, UserRepository users) { this.jdbc=jdbc; this.users=users; }
 java.util.List<?> load(Long departmentId) { return jdbc.queryForList("SELECT id,department_id FROM app_user WHERE department_id=?",departmentId); }
}
