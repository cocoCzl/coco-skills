package primary;
interface UserRepository extends org.springframework.data.jpa.repository.JpaRepository<User,Long> {
 @org.springframework.data.jpa.repository.Query("select u from User u where u.id=:id") User lookup(Long id);
 User findByIdValue(Long id);
}
