from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "java-code-to-erd/scripts"))
from lib.core import analyze_project, canonical_json, validate_model  # noqa: E402


class AcceptanceMatrixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="java-code-to-erd-acceptance-")
        self.project = Path(self.temp.name) / "project"
        self.project.mkdir()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write(self, name: str, content: str) -> Path:
        path = self.project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def analyze(self, **kwargs):
        model, artifacts, warnings = analyze_project(self.project, full_rescan=True, **kwargs)
        self.assertEqual([], validate_model(model))
        project = self.project.resolve()
        return model, {Path(path).resolve().relative_to(project).as_posix() for path in artifacts}, warnings

    def test_discovery_has_no_silent_limit_and_excludes_non_production_trees(self) -> None:
        self.write("pom.xml", "<project><modules><module>domain</module></modules></project>")
        self.write("domain/build.gradle", "plugins { id 'java' }")
        for index in range(260):
            self.write(f"domain/src/main/resources/sql/q{index:03d}.sql", f"SELECT id FROM table_{index:03d};")
        self.write("domain/src/test/resources/ignored.sql", "SELECT secret FROM test_only;")
        self.write("domain/target/generated.sql", "SELECT secret FROM generated_only;")
        model, _, _ = self.analyze()
        self.assertGreaterEqual(model["coverage"]["discovered"], 262)
        self.assertNotIn("test_only", {item["name"] for item in model["databaseObjects"]})
        self.assertNotIn("generated_only", {item["name"] for item in model["databaseObjects"]})
        self.assertTrue(model["applications"][0]["modules"])

    def test_four_dialects_and_all_basic_dml_are_detected(self) -> None:
        cases = {
            "mysql": "jdbc:mysql://localhost/demo",
            "postgresql": "jdbc:postgresql://localhost/demo",
            "oracle": "jdbc:oracle:thin:@localhost:1521/demo",
            "sqlserver": "jdbc:sqlserver://localhost;databaseName=demo",
        }
        for dialect, url in cases.items():
            with self.subTest(dialect=dialect):
                project = self.project / dialect
                project.mkdir()
                (project / "application.properties").write_text(f"spring.datasource.url={url}\n", encoding="utf-8")
                (project / "query.sql").write_text("SELECT a.id FROM account a; INSERT INTO account(id,name) VALUES (?,?); UPDATE account SET name=? WHERE id=?; DELETE FROM account WHERE id=?; MERGE INTO account a USING staging s ON a.id=s.id WHEN MATCHED THEN UPDATE SET a.name=s.name;", encoding="utf-8")
                model, _, _ = analyze_project(project, full_rescan=True)
                self.assertNotEqual(["UNKNOWN"], model["dialects"])
                self.assertEqual({"READ", "INSERT", "UPDATE", "DELETE"}, {op["kind"] for op in model["operations"]})

    def test_flyway_rename_drop_fk_and_history_restore_current_shape(self) -> None:
        self.write("src/main/resources/db/migration/V1__base.sql", "CREATE TABLE parent(id BIGINT PRIMARY KEY); CREATE TABLE child(id BIGINT PRIMARY KEY,parent_id BIGINT,CONSTRAINT fk_child_parent FOREIGN KEY(parent_id) REFERENCES parent(id));")
        self.write("src/main/resources/db/migration/V2__rename.sql", "ALTER TABLE child RENAME TO child_order; ALTER TABLE child_order RENAME COLUMN parent_id TO owner_id;")
        self.write("src/main/resources/db/migration/V3__drop_fk.sql", "ALTER TABLE child_order DROP CONSTRAINT fk_child_parent;")
        model, _, _ = self.analyze()
        child = next(item for item in model["databaseObjects"] if item["name"] == "child_order")
        self.assertIn("child", child["historicalNames"])
        self.assertIn("owner_id", {column["name"] for column in child["columns"]})
        self.assertFalse(any("DDL_FOREIGN_KEY" in rel["sourceTypes"] for rel in model["relationships"]))

    def test_liquibase_xml_json_yaml_sql_and_include_cycle_degrade_safely(self) -> None:
        self.write("src/main/resources/db/changelog/a.xml", '<databaseChangeLog><include file="b.xml"/><changeSet id="1" author="x" context="dev"><createTable tableName="xml_table"><column name="id" type="BIGINT"><constraints primaryKey="true"/></column></createTable></changeSet></databaseChangeLog>')
        self.write("src/main/resources/db/changelog/b.xml", '<databaseChangeLog><include file="a.xml"/></databaseChangeLog>')
        self.write("src/main/resources/db/changelog/c.json", json.dumps({"databaseChangeLog": [{"changeSet": {"changes": [{"createTable": {"tableName": "json_table", "columns": [{"column": {"name": "id", "type": "BIGINT"}}]}}]}}]}))
        self.write("src/main/resources/db/changelog/d.yaml", "databaseChangeLog:\n  - changeSet:\n      changes:\n        - createTable:\n            tableName: yaml_table\n            columns:\n              - column:\n                  name: id\n                  type: BIGINT\n")
        self.write("src/main/resources/db/changelog/e.sql", "--liquibase formatted sql\nCREATE TABLE sql_table(id BIGINT PRIMARY KEY);")
        model, _, _ = self.analyze()
        self.assertTrue({"xml_table", "json_table", "yaml_table", "sql_table"}.issubset({item["name"] for item in model["databaseObjects"]}))
        self.assertEqual("PARTIAL", model["analysisStatus"])
        self.assertTrue(any(item["kind"] == "LIQUIBASE_INCLUDE_CYCLE" for item in model["unresolved"]))

    def test_advanced_jpa_structures_preserve_embedded_override_and_storage_links(self) -> None:
        self.write("pom.xml", "<project><dependencies><dependency><artifactId>spring-boot-starter-data-jpa</artifactId></dependency></dependencies></project>")
        self.write("src/main/java/x/Key.java", "package x;\n@jakarta.persistence.Embeddable\nclass Key {\n @jakarta.persistence.Column(name=\"tenant_id\") private Long tenantId;\n @jakarta.persistence.Column(name=\"local_id\") private Long localId;\n}\n")
        self.write("src/main/java/x/Base.java", "package x;\n@jakarta.persistence.Entity\n@jakarta.persistence.Table(name=\"base_record\")\n@jakarta.persistence.Inheritance(strategy=jakarta.persistence.InheritanceType.JOINED)\nclass Base { @jakarta.persistence.Id private Long id; }\n")
        self.write("src/main/java/x/Detail.java", "package x;\n@jakarta.persistence.Entity\n@jakarta.persistence.Table(name=\"detail_record\")\n@jakarta.persistence.SecondaryTable(name=\"detail_extra\")\nclass Detail extends Base {\n @jakarta.persistence.EmbeddedId\n @jakarta.persistence.AttributeOverride(name=\"localId\", column=@jakarta.persistence.Column(name=\"detail_id\"))\n private Key key;\n @jakarta.persistence.ElementCollection\n @jakarta.persistence.CollectionTable(name=\"detail_tags\", joinColumns=@jakarta.persistence.JoinColumn(name=\"detail_id\"))\n private java.util.Set<String> tags;\n}\n")
        model, _, _ = self.analyze()
        objects = {item["name"]: item for item in model["databaseObjects"]}
        self.assertTrue({"base_record", "detail_record", "detail_extra", "detail_tags"}.issubset(objects))
        self.assertIn("detail_id", {column["name"] for column in objects["detail_record"]["columns"]})
        self.assertGreaterEqual(sum("ORM_RELATION" in rel["sourceTypes"] for rel in model["relationships"]), 2)

    def test_spring_data_query_apis_and_derived_methods_add_field_usage(self) -> None:
        self.write("src/main/java/x/Order.java", "package x;\n@jakarta.persistence.Entity\n@jakarta.persistence.Table(name=\"orders\")\nclass Order { @jakarta.persistence.Id Long id; @jakarta.persistence.Column(name=\"status\") String status; }\n")
        self.write("src/main/java/x/Repo.java", 'package x; interface Repo extends org.springframework.data.jpa.repository.JpaRepository<Order,Long> { @org.springframework.data.jpa.repository.Query("select o from Order o where o.status=:s") java.util.List<Order> search(String s); java.util.List<Order> findByStatus(String s); default void spec(){ Object x=root.get("status"); Object y=QOrder.order.status; } }')
        model, _, _ = self.analyze()
        order = next(item for item in model["databaseObjects"] if item["name"] == "orders")
        operations = [op for op in model["operations"] if op["databaseObjectId"] == order["id"]]
        self.assertTrue(operations)
        self.assertIn("status", {column for op in operations for column in op["columnNames"]})

    def test_json_and_map_get_keys_are_not_database_fields_or_unresolved_queries(self) -> None:
        self.write("schema.sql", "CREATE TABLE orders(id BIGINT PRIMARY KEY);")
        self.write("src/main/java/x/PayloadReader.java", 'package x; class PayloadReader { void read(java.util.Map<String,Object> payload, Object json) { payload.get("order_id"); json.get("display_name"); } }')
        model, _, _ = self.analyze()
        orders = next(item for item in model["databaseObjects"] if item["name"] == "orders")
        self.assertEqual({"id"}, {column["name"] for column in orders["columns"]})
        self.assertFalse(any(item["kind"] == "QUERY_API_CONTEXT" for item in model["unresolved"]))
        self.assertEqual("COMPLETE", model["analysisStatus"])

    def test_cross_class_value_flow_keeps_the_full_location_chain_and_stops_on_ambiguity(self) -> None:
        self.write("src/main/java/x/User.java", "package x;\n@jakarta.persistence.Entity\n@jakarta.persistence.Table(name=\"app_user\")\nclass User { @jakarta.persistence.Id Long id; Long getId(){return id;} }\n")
        self.write("src/main/java/x/Order.java", "package x;\n@jakarta.persistence.Entity\n@jakarta.persistence.Table(name=\"orders\")\nclass Order { @jakarta.persistence.Id Long id; @jakarta.persistence.Column(name=\"user_id\") Long userId; }\n")
        self.write("src/main/java/x/OrderMapper.java", "package x; interface OrderMapper extends com.baomidou.mybatisplus.core.mapper.BaseMapper<Order> { Order findByUserId(Long userId); }")
        self.write("src/main/java/x/OrderService.java", "package x; class OrderService { OrderMapper orderMapper; void byUser(Long userId){ orderMapper.findByUserId(userId); } }")
        self.write("src/main/java/x/Facade.java", "package x; class Facade { OrderService service; void load(User user){ Long id=user.getId(); service.byUser(id); } }")
        model, _, _ = self.analyze()
        relation = next(rel for rel in model["relationships"] if "CODE_INFERRED" in rel["sourceTypes"])
        locations = {ev["file"] for ev in model["evidence"] if ev["id"] in relation["evidenceIds"]}
        self.assertIn("src/main/java/x/Facade.java", locations)
        self.assertIn("src/main/java/x/OrderService.java", locations)
        self.assertGreaterEqual(len(relation["evidenceIds"]), 2)

    def test_mybatis_dynamic_provider_result_map_and_plus_wrapper(self) -> None:
        self.write("pom.xml", "<project><dependencies><dependency><artifactId>mybatis-plus</artifactId></dependency></dependencies></project>")
        self.write("src/main/java/x/Account.java", "package x;\n@com.baomidou.mybatisplus.annotation.TableName(\"account\")\nclass Account { @com.baomidou.mybatisplus.annotation.TableId private Long id; @com.baomidou.mybatisplus.annotation.TableLogic private Integer deleted; @com.baomidou.mybatisplus.annotation.Version private Integer version; }\n")
        self.write("src/main/java/x/Mapper.java", 'package x; interface Mapper extends com.baomidou.mybatisplus.core.mapper.BaseMapper<Account> { @org.apache.ibatis.annotations.SelectProvider(type=SqlProvider.class,method="find") Account find(); default void q(){ com.baomidou.mybatisplus.core.conditions.query.QueryWrapper<Account> q=null; q.eq("deleted",0).orderByAsc("id"); } }')
        self.write("src/main/java/x/SqlProvider.java", 'package x; class SqlProvider { static String find(){ return "SELECT a.id,a.deleted FROM account a LEFT JOIN profile p ON a.id=p.account_id"; } }')
        self.write("src/main/resources/x/Mapper.xml", '<mapper namespace="x.Mapper"><sql id="cols">a.id,a.deleted</sql><resultMap id="rm" type="x.AccountView"><association property="profile" javaType="x.Profile" column="id"/></resultMap><select id="dynamic" resultMap="rm">SELECT <include refid="cols"/> FROM account a <if test="withProfile">LEFT JOIN profile p ON a.id=p.account_id</if></select></mapper>')
        model, _, _ = self.analyze()
        self.assertFalse(any(item["kind"] == "MYBATIS_PROVIDER" for item in model["unresolved"]))
        self.assertTrue(any(rel["status"] == "CONDITIONAL" for rel in model["relationships"]))
        self.assertTrue(any("RESULT_MAPPING" in rel["sourceTypes"] for rel in model["relationships"]))
        account = next(item for item in model["databaseObjects"] if item["name"] == "account")
        usages = {usage for column in account["columns"] for usage in column["usages"]}
        self.assertTrue({"LOGIC_DELETE", "OPTIMISTIC_LOCK"}.issubset(usages))

    def test_jdbc_batches_result_columns_routine_calls_and_dynamic_tables_degrade(self) -> None:
        self.write("src/main/java/x/JdbcDao.java", 'package x; class JdbcDao { void run(java.sql.Connection c) throws Exception { String q="SELECT id,user_id FROM orders"; java.sql.PreparedStatement p=c.prepareStatement(q); p.addBatch(); p.executeBatch(); java.sql.ResultSet r=p.executeQuery(); r.getLong("user_id"); c.prepareCall("{call external_reconcile(?)}").execute(); String dynamic="SELECT id FROM audit_${tenantId}"; } }')
        model, _, _ = self.analyze()
        orders = next(item for item in model["databaseObjects"] if item["name"] == "orders")
        self.assertIn("user_id", {column["name"] for column in orders["columns"]})
        self.assertTrue(any(item["dynamicPattern"] for item in model["databaseObjects"]))
        self.assertTrue(any(op["kind"] == "CALL" for op in model["operations"]))
        self.assertEqual("PARTIAL", model["analysisStatus"])

    def test_multi_datasource_and_profile_selection_keep_identity_separate(self) -> None:
        self.write("application.properties", "spring.datasource.primary.url=jdbc:mysql://localhost/a\nspring.datasource.audit.url=jdbc:postgresql://localhost/b\n")
        self.write("application-dev.properties", "feature=true")
        self.write("application-prod.properties", "feature=false")
        self.write("src/main/resources/primary/schema.sql", "CREATE TABLE shared(id BIGINT PRIMARY KEY);")
        self.write("src/main/resources/audit/schema.sql", "CREATE TABLE shared(id BIGINT PRIMARY KEY);")
        model, _, _ = self.analyze(profile="dev")
        shared = [item for item in model["databaseObjects"] if item["name"] == "shared"]
        self.assertEqual(2, len(shared))
        self.assertEqual(2, len({item["dataSourceId"] for item in shared}))
        self.assertEqual({"dev"}, {item["profile"] for item in shared})

    def test_human_review_is_preserved_and_never_becomes_physical_dbml(self) -> None:
        self.write("schema.sql", "CREATE TABLE account(id BIGINT PRIMARY KEY,owner_id BIGINT); CREATE TABLE owner(id BIGINT PRIMARY KEY);")
        first, _, _ = self.analyze()
        data_root = self.project / "data/java-code-to-erd"
        project_dir = next(data_root.iterdir())
        review = {"schemaVersion": "1.0", "reviews": [{"id": "manual-1", "action": "CONFIRM", "fromTable": "account", "fromColumns": ["owner_id"], "toTable": "owner", "toColumns": ["id"], "reason": "team confirmation"}]}
        (project_dir / "user-review.json").write_text(canonical_json(review), encoding="utf-8")
        model, _, _ = self.analyze()
        relation = next(rel for rel in model["relationships"] if "USER_CONFIRMED" in rel["sourceTypes"])
        self.assertEqual("USER_CONFIRMED", relation["conclusionKind"])
        dbml = (self.project / "reports/java-code-to-erd/database.dbml").read_text(encoding="utf-8")
        self.assertNotIn("Ref:", dbml)
        self.assertTrue((project_dir / "user-review.json").exists())
        self.assertTrue(first["candidates"])

    def test_large_and_wide_model_generates_stable_overview_clusters_and_truncation(self) -> None:
        columns = ",".join(["id BIGINT PRIMARY KEY"] + [f"field_{index} VARCHAR(20)" for index in range(25)])
        ddl = [f"CREATE TABLE table_00({columns});"]
        for index in range(1, 28):
            ddl.append(f"CREATE TABLE table_{index:02d}(id BIGINT PRIMARY KEY,parent_id BIGINT NOT NULL,FOREIGN KEY(parent_id) REFERENCES table_{index-1:02d}(id));")
        self.write("schema.sql", "\n".join(ddl))
        model, artifacts, _ = self.analyze()
        self.assertIn("reports/java-code-to-erd/database-erd-overview.mmd", artifacts)
        self.assertTrue(any("/erd/cluster-" in path for path in artifacts))
        erd = (self.project / "reports/java-code-to-erd/database-erd.mmd").read_text(encoding="utf-8")
        self.assertIn("omitted_", erd)
        overview = (self.project / "reports/java-code-to-erd/database-erd-overview.mmd").read_text(encoding="utf-8")
        self.assertIn("flowchart LR", overview)

    def test_all_declared_unsupported_paths_degrade_without_losing_plain_sql(self) -> None:
        self.write("pom.xml", "<project><dependencies><dependency><groupId>org.jooq</groupId></dependency><dependency><groupId>org.jdbi</groupId></dependency><dependency><groupId>io.ebean</groupId></dependency><dependency><artifactId>spring-data-jdbc</artifactId></dependency><dependency><artifactId>spring-data-r2dbc</artifactId></dependency><dependency><artifactId>byte-buddy</artifactId></dependency><dependency><artifactId>spring-cloud-config</artifactId></dependency></dependencies></project>")
        self.write("src/main/java/x/Dynamic.java", 'package x; class Dynamic { void x() throws Exception { Class.forName("x.GeneratedDao"); } String sql="SELECT id FROM retained_sql"; }')
        model, _, _ = self.analyze()
        self.assertEqual("PARTIAL", model["analysisStatus"])
        self.assertIn("retained_sql", {item["name"] for item in model["databaseObjects"]})
        unsupported = {item["message"] for item in model["unresolved"] if item["kind"] == "UNSUPPORTED_FRAMEWORK"}
        self.assertGreaterEqual(len(unsupported), 7)

    def test_core_outputs_are_model_derived_language_aware_and_evidence_minimal(self) -> None:
        self.write("schema.sql", "CREATE TABLE parent(id BIGINT PRIMARY KEY); CREATE TABLE child(id BIGINT PRIMARY KEY,parent_id BIGINT REFERENCES parent(id));")
        model, artifacts, warnings = self.analyze(language="en")
        self.assertTrue(all("will install" not in warning.lower() for warning in warnings))
        self.assertTrue({"reports/java-code-to-erd/database-model.json", "reports/java-code-to-erd/database-analysis.md", "reports/java-code-to-erd/database-erd.mmd", "reports/java-code-to-erd/database.dbml"}.issubset(artifacts))
        report = (self.project / "reports/java-code-to-erd/database-analysis.md").read_text(encoding="utf-8")
        self.assertIn("Java Project Database Model Analysis", report)
        self.assertTrue(all(set(item) == {"id", "file", "startLine", "endLine", "sourceType"} for item in model["evidence"]))
        self.assertTrue(all(not Path(item["file"]).is_absolute() for item in model["evidence"]))

    def test_visual_verification_cannot_be_marked_without_every_svg(self) -> None:
        self.write("schema.sql", "CREATE TABLE visible_table(id BIGINT PRIMARY KEY);")
        model, _, _ = self.analyze()
        self.assertIn(model["visualStatus"], {"SOURCE_ONLY", "RENDERER_AVAILABLE_NOT_VERIFIED"})
        from lib.core import confirm_visual_verification
        with self.assertRaises(ValueError):
            confirm_visual_verification(self.project)

    def test_comprehensive_mixed_fixture_is_stable_safe_and_incrementally_equivalent(self) -> None:
        source = ROOT / "tests/fixtures/java_code_to_erd/comprehensive-project"
        shutil.copytree(source, self.project, dirs_exist_ok=True)
        first, first_artifacts, _ = self.analyze()
        first_json = canonical_json(first)
        incremental, _, _ = analyze_project(self.project)
        rescanned, _, _ = analyze_project(self.project, full_rescan=True)
        self.assertEqual(first_json, canonical_json(incremental))
        self.assertEqual(first_json, canonical_json(rescanned))
        self.assertEqual(2, len(first["applications"]))
        self.assertGreaterEqual(len(first["dataSources"]), 3)
        self.assertTrue({"JPA_HIBERNATE", "MYBATIS", "MYBATIS_PLUS", "JDBC_TEMPLATE", "JDBC", "FLYWAY", "LIQUIBASE"}.issubset(first["technologies"]))
        self.assertEqual("PARTIAL", first["analysisStatus"])
        self.assertTrue(any(item["kind"] == "UNSUPPORTED_FRAMEWORK" for item in first["unresolved"]))
        self.assertTrue(any(rel["status"] == "CONDITIONAL" for rel in first["relationships"]))
        self.assertTrue({"reports/java-code-to-erd/database-model.json", "reports/java-code-to-erd/database-analysis.md", "reports/java-code-to-erd/database-erd.mmd", "reports/java-code-to-erd/database.dbml"}.issubset(first_artifacts))
        self.assertTrue(all(not Path(ev["file"]).is_absolute() for ev in first["evidence"]))


if __name__ == "__main__":
    unittest.main()
