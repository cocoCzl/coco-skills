package primary;
@jakarta.persistence.Entity
@jakarta.persistence.Table(name="app_user")
class User {
 @jakarta.persistence.Id private Long id;
 @jakarta.persistence.ManyToOne(optional=false)
 @jakarta.persistence.JoinColumn(name="department_id", referencedColumnName="id")
 private Department department;
}
