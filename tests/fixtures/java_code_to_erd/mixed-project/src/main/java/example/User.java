package example;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.Table;

@Entity
@Table(name = "app_user")
public class User {
    @Id
    private Long id;

    @Column(name = "username", nullable = false)
    private String username;

    @ManyToOne(optional = false)
    @JoinColumn(name = "dept_id", referencedColumnName = "id")
    private Department department;
}
