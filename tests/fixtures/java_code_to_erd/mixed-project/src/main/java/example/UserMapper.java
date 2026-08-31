package example;

public interface UserMapper {
    String SQL = "SELECT u.id, u.dept_id, d.id FROM app_user u LEFT JOIN department d ON u.dept_id = d.id";
}
