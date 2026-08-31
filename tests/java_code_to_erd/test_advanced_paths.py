from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "java-code-to-erd/scripts/java_code_to_erd.py"


class AdvancedPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="java-code-to-erd-advanced-")
        self.project = Path(self.temp.name) / "project"; self.project.mkdir()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write(self, name: str, content: str) -> None:
        path = self.project / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(content, encoding="utf-8")

    def analyze(self, *extra: str) -> dict:
        result = subprocess.run([sys.executable, str(CLI), "analyze", "--project", str(self.project), "--full-rescan", *extra], cwd=ROOT, text=True, capture_output=True, check=False)
        self.assertEqual(0, result.returncode, result.stderr or result.stdout)
        return json.loads((self.project / "reports/java-code-to-erd/database-model.json").read_text(encoding="utf-8"))

    def test_sql_cte_using_writes_and_non_equality_dependency(self) -> None:
        self.write("src/main/resources/schema.sql", "CREATE TABLE a (id BIGINT PRIMARY KEY, value INT); CREATE TABLE b (id BIGINT PRIMARY KEY, value INT);")
        self.write("src/main/resources/query.sql", "WITH recent AS (SELECT id FROM a) SELECT * FROM recent r JOIN b USING(id) WHERE r.value > b.value; INSERT INTO a(id,value) VALUES (?,?); UPDATE b SET value=? WHERE id=?;")
        model = self.analyze(); names = {o["name"] for o in model["databaseObjects"]}
        self.assertNotIn("recent", names)
        self.assertTrue(any("SQL_JOIN" in r["sourceTypes"] for r in model["relationships"]))
        self.assertTrue(any("OBJECT_DEPENDENCY" in r["sourceTypes"] for r in model["relationships"]))
        self.assertEqual({"INSERT", "READ", "UPDATE"}, {o["kind"] for o in model["operations"]})

    def test_composite_constraints_indexes_and_database_object_dependencies(self) -> None:
        self.write("src/main/resources/schema.sql", """
CREATE TABLE parent (tenant_id BIGINT, id BIGINT, PRIMARY KEY(tenant_id,id));
CREATE TABLE child (tenant_id BIGINT, parent_id BIGINT, UNIQUE(tenant_id,parent_id), FOREIGN KEY(tenant_id,parent_id) REFERENCES parent(tenant_id,id));
CREATE INDEX ix_child_parent ON child(parent_id);
CREATE VIEW child_view AS SELECT c.parent_id FROM child c;
CREATE FUNCTION count_children() RETURNS INT BEGIN SELECT count(*) FROM child; END;
""")
        model = self.analyze(); objects = {o["name"]: o for o in model["databaseObjects"]}
        self.assertEqual([["tenant_id", "id"]], objects["parent"]["primaryKeys"])
        self.assertTrue(objects["child"]["indexes"])
        fk = next(r for r in model["relationships"] if "DDL_FOREIGN_KEY" in r["sourceTypes"])
        self.assertEqual(2, len(fk["from"]["columnIds"]))
        self.assertTrue(any("OBJECT_DEPENDENCY" in r["sourceTypes"] for r in model["relationships"]))
        self.assertEqual("VIEW", objects["child_view"]["objectType"])
        self.assertEqual("FUNCTION", objects["count_children"]["objectType"])

    def test_liquibase_forward_changes_ignore_rollback_and_detect_missing_include(self) -> None:
        self.write("src/main/resources/db/changelog/master.xml", """<databaseChangeLog xmlns=\"http://www.liquibase.org/xml/ns/dbchangelog\">
<include file=\"missing.xml\"/><changeSet id=\"1\" author=\"x\"><createTable tableName=\"account\"><column name=\"id\" type=\"BIGINT\"><constraints primaryKey=\"true\"/></column></createTable><addColumn tableName=\"account\"><column name=\"email\" type=\"VARCHAR(120)\"/></addColumn><rollback><dropTable tableName=\"account\"/></rollback></changeSet></databaseChangeLog>""")
        model = self.analyze(); account = next(o for o in model["databaseObjects"] if o["name"] == "account")
        self.assertEqual({"id", "email"}, {c["name"] for c in account["columns"]})
        self.assertEqual("PARTIAL", model["analysisStatus"])
        self.assertTrue(any(u["kind"] == "LIQUIBASE_INCLUDE_MISSING" for u in model["unresolved"]))

    def test_property_access_embedded_key_jpql_and_derived_query(self) -> None:
        self.write("pom.xml", "<project><dependencies><dependency><artifactId>spring-boot-starter-data-jpa</artifactId></dependency></dependencies></project>")
        self.write("src/main/java/x/OrderId.java", "package x; @jakarta.persistence.Embeddable class OrderId { @jakarta.persistence.Column(name=\"tenant_id\") Long tenantId; @jakarta.persistence.Column(name=\"order_id\") Long orderId; }")
        self.write("src/main/java/x/Order.java", "package x; @jakarta.persistence.Entity @jakarta.persistence.Table(name=\"orders\") class Order { private OrderId id; @jakarta.persistence.EmbeddedId public OrderId getId(){return id;} @jakarta.persistence.Column(name=\"status\") public String getStatus(){return null;} }")
        self.write("src/main/java/x/OrderRepository.java", "package x; interface OrderRepository extends org.springframework.data.jpa.repository.JpaRepository<Order,OrderId> { @org.springframework.data.jpa.repository.Query(\"select o from Order o where o.status = :status\") java.util.List<Order> lookup(String status); java.util.List<Order> findByStatus(String status); }")
        model = self.analyze(); orders = next(o for o in model["databaseObjects"] if o["name"] == "orders")
        self.assertIn("status", {c["name"] for c in orders["columns"]})
        self.assertTrue(any(o["databaseObjectId"] == orders["id"] for o in model["operations"]))
        self.assertNotIn("o", {o["name"] for o in model["databaseObjects"]})

    def test_jdbc_resultset_and_cross_method_value_flow(self) -> None:
        self.write("src/main/java/x/User.java", "package x; @jakarta.persistence.Entity @jakarta.persistence.Table(name=\"app_user\") class User { @jakarta.persistence.Id Long id; Long getId(){return id;} }")
        self.write("src/main/java/x/Order.java", "package x; @jakarta.persistence.Entity @jakarta.persistence.Table(name=\"orders\") class Order { @jakarta.persistence.Id Long id; @jakarta.persistence.Column(name=\"user_id\") Long userId; }")
        self.write("src/main/java/x/OrderMapper.java", "package x; interface OrderMapper extends com.baomidou.mybatisplus.core.mapper.BaseMapper<Order> { Order findByUserId(Long id); }")
        self.write("src/main/java/x/Service.java", "package x; class Service { OrderMapper orderMapper; void load(User user){ orderMapper.findByUserId(user.getId()); } void jdbc(java.sql.Connection c) throws Exception { String sql=\"SELECT id,user_id FROM orders\"; java.sql.ResultSet rs=c.prepareStatement(sql).executeQuery(); rs.getLong(\"user_id\"); } }")
        model = self.analyze()
        self.assertTrue(any("CODE_INFERRED" in r["sourceTypes"] for r in model["relationships"]))
        orders = next(o for o in model["databaseObjects"] if o["name"] == "orders")
        self.assertIn("user_id", {c["name"] for c in orders["columns"]})

    def test_two_boot_apps_keep_same_table_separate(self) -> None:
        for app in ("app-a", "app-b"):
            self.write(f"{app}/pom.xml", "<project><build><plugins><plugin><artifactId>spring-boot-maven-plugin</artifactId></plugin></plugins></build></project>")
            self.write(f"{app}/src/main/java/x/App.java", "package x; @org.springframework.boot.autoconfigure.SpringBootApplication class App {}")
            self.write(f"{app}/src/main/resources/schema.sql", "CREATE TABLE common_table (id BIGINT PRIMARY KEY);")
        model = self.analyze()
        common = [o for o in model["databaseObjects"] if o["name"] == "common_table"]
        self.assertEqual(2, len(common)); self.assertEqual(2, len({o["id"] for o in common})); self.assertEqual(2, len(model["applications"]))

    def test_unsupported_framework_degrades_but_plain_sql_survives(self) -> None:
        self.write("pom.xml", "<project><dependencies><dependency><groupId>org.jooq</groupId><artifactId>jooq</artifactId></dependency></dependencies></project>")
        self.write("src/main/java/x/Dao.java", "package x; class Dao { String sql=\"SELECT id FROM audit_log\"; }")
        model = self.analyze()
        self.assertEqual("PARTIAL", model["analysisStatus"]); self.assertIn("audit_log", {o["name"] for o in model["databaseObjects"]})
        self.assertTrue(any(u["kind"] == "UNSUPPORTED_FRAMEWORK" for u in model["unresolved"]))


if __name__ == "__main__":
    unittest.main()
