from __future__ import annotations

import copy
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "java-code-to-erd"
CLI = SKILL / "scripts" / "java_code_to_erd.py"
LAUNCHER = SKILL / "scripts" / "launch.py"
FIXTURE = ROOT / "tests" / "fixtures" / "java_code_to_erd" / "mixed-project"
sys.path.insert(0, str(SKILL / "scripts"))

from lib.core import analyze_project, validate_model  # noqa: E402


class JavaCodeToErdTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="java-code-to-erd-test-")
        self.project = Path(self.temp.name) / "project"
        shutil.copytree(FIXTURE, self.project)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_cli(self, *args: str, expect: int = 0) -> dict:
        result = subprocess.run(
            [sys.executable, str(CLI), *args],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(expect, result.returncode, result.stderr or result.stdout)
        return json.loads(result.stdout)

    def analyze(self, *extra: str) -> tuple[dict, Path]:
        result = self.run_cli("analyze", "--project", str(self.project), *extra)
        model_path = self.project / "reports" / "java-code-to-erd" / "database-model.json"
        return json.loads(model_path.read_text(encoding="utf-8")), model_path.parent

    def test_doctor_reports_explicit_safety_boundary(self) -> None:
        result = self.run_cli("doctor", "--project", str(self.project))
        self.assertEqual("READY", result["data_status"])
        self.assertEqual(
            {
                "connectsDatabase": False,
                "runsProject": False,
                "buildsProject": False,
                "usesNetwork": False,
                "installsSoftware": False,
            },
            result["data"]["safety"],
        )

    def test_bundled_source_cross_check_compiles_for_jdk_8(self) -> None:
        javac = shutil.which("javac")
        if not javac:
            self.skipTest("javac is unavailable")
        helper = SKILL / "scripts" / "java" / "SourceFactExtractor.java"
        helper_source = helper.read_text(encoding="utf-8")
        self.assertNotIn("List.of(", helper_source)
        with tempfile.TemporaryDirectory(prefix="java-code-to-erd-jdk8-") as directory:
            output = Path(directory) / "classes"
            result = subprocess.run(
                [javac, "-source", "1.8", "-target", "1.8", "-d", str(output), str(helper)],
                text=True, capture_output=True, check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr or result.stdout)

    def test_optional_jdk_cross_check_does_not_degrade_database_analysis(self) -> None:
        with patch("lib.core.verify_java_syntax_with_jdk", return_value="Local JDK syntax cross-check is unavailable."):
            model, _, _ = analyze_project(self.project, full_rescan=True)
        output = self.project / "reports" / "java-code-to-erd"
        self.assertEqual("COMPLETE", model["analysisStatus"])
        self.assertEqual(
            [{"kind": "JDK_SOURCE_VERIFICATION", "message": "Local JDK syntax cross-check is unavailable."}],
            model["environmentDiagnostics"],
        )
        report = output / "database-analysis.md"
        self.assertIn("环境诊断", report.read_text(encoding="utf-8"))

    def test_missing_mermaid_cli_keeps_database_analysis_complete(self) -> None:
        original_which = shutil.which
        with patch("lib.core.shutil.which", side_effect=lambda name: None if name == "mmdc" else original_which(name)):
            model, _, warnings = analyze_project(self.project, full_rescan=True)
        self.assertEqual("COMPLETE", model["analysisStatus"])
        self.assertEqual("SOURCE_ONLY", model["visualStatus"])
        self.assertTrue(any("Mermaid CLI not installed" in warning for warning in warnings))

    def test_status_envelope_maps_complete_partial_and_failed(self) -> None:
        complete = self.run_cli("analyze", "--project", str(self.project), "--full-rescan")
        self.assertEqual("completed", complete["status"])
        self.assertEqual("COMPLETE", complete["data_status"])
        (self.project / "pom.xml").write_text("<project><dependency><groupId>org.jooq</groupId></dependency></project>", encoding="utf-8")
        partial = self.run_cli("analyze", "--project", str(self.project), "--full-rescan")
        self.assertEqual("degraded", partial["status"])
        self.assertEqual("PARTIAL", partial["data_status"])
        failed = self.run_cli("analyze", "--project", str(self.project / "missing"), expect=1)
        self.assertEqual("error", failed["status"])
        self.assertEqual("FAILED", failed["data_status"])

    def test_bootstrap_works_from_the_system_python_without_installing(self) -> None:
        system_python = Path("/usr/bin/python3")
        if not system_python.exists():
            self.skipTest("system Python is unavailable")
        result = subprocess.run(
            [str(system_python), str(LAUNCHER), "doctor", "--project", str(self.project)],
            cwd=ROOT, text=True, capture_output=True, check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr or result.stdout)
        payload = json.loads(result.stdout)
        self.assertEqual("READY", payload["data_status"])
        self.assertFalse(payload["data"]["safety"]["installsSoftware"])

    def test_mixed_project_merges_evidence_without_inventing_tables(self) -> None:
        model, output = self.analyze()
        self.assertEqual({"app_user", "department"}, {o["name"] for o in model["databaseObjects"]})
        self.assertNotIn("test_only_table", output.joinpath("database-model.json").read_text(encoding="utf-8"))
        self.assertEqual(1, len(model["relationships"]))
        relation = model["relationships"][0]
        self.assertEqual(["DDL_FOREIGN_KEY", "ORM_RELATION", "SQL_JOIN"], relation["sourceTypes"])
        self.assertEqual("MANY_TO_ONE", relation["constraintCardinality"])
        self.assertEqual("MANY_TO_ONE", relation["codeCardinality"])
        self.assertEqual("REQUIRED", relation["optionality"])
        self.assertFalse(validate_model(model))
        for item in model["evidence"]:
            self.assertFalse(Path(item["file"]).is_absolute())
            self.assertNotIn("snippet", item)
            self.assertLessEqual(item["startLine"], item["endLine"])

    def test_core_artifacts_are_byte_stable(self) -> None:
        _, output = self.analyze()
        names = ["database-model.json", "database-erd.mmd", "database.dbml", "database-analysis.md"]
        before = {name: output.joinpath(name).read_bytes() for name in names}
        self.analyze()
        after = {name: output.joinpath(name).read_bytes() for name in names}
        self.assertEqual(before, after)

    def test_dbml_ref_is_created_only_for_ddl_foreign_key(self) -> None:
        _, output = self.analyze()
        dbml = output.joinpath("database.dbml").read_text(encoding="utf-8")
        self.assertEqual(1, sum(line.startswith("Ref:") for line in dbml.splitlines()))
        self.project.joinpath("src/main/resources/db/migration/V1__schema.sql").unlink()
        _, output = self.analyze()
        dbml = output.joinpath("database.dbml").read_text(encoding="utf-8")
        self.assertFalse(any(line.startswith("Ref:") for line in dbml.splitlines()))

    def test_incremental_analysis_removes_deleted_evidence(self) -> None:
        model, _ = self.analyze()
        self.assertIn("DDL_FOREIGN_KEY", model["relationships"][0]["sourceTypes"])
        self.project.joinpath("src/main/resources/db/migration/V1__schema.sql").unlink()
        model, _ = self.analyze()
        self.assertNotIn("DDL_FOREIGN_KEY", model["relationships"][0]["sourceTypes"])
        self.assertFalse(any("V1__schema.sql" in e["file"] for e in model["evidence"]))

    def test_incremental_context_change_matches_full_rescan(self) -> None:
        self.analyze()
        pom = self.project / "pom.xml"
        pom.write_text(pom.read_text(encoding="utf-8").replace("<project>", "<project><properties><java.version>21</java.version></properties>"), encoding="utf-8")
        incremental, output = self.analyze()
        incremental_files = {name: output.joinpath(name).read_bytes() for name in ("database-model.json", "database-erd.mmd", "database.dbml", "database-analysis.md")}
        full, output = self.analyze("--full-rescan")
        full_files = {name: output.joinpath(name).read_bytes() for name in incremental_files}
        self.assertEqual(incremental, full)
        self.assertEqual(incremental_files, full_files)

    def test_failed_publish_preserves_previous_valid_report(self) -> None:
        _, output = self.analyze()
        before = output.joinpath("database-model.json").read_bytes()
        invalid_output = self.project / "blocked-output"
        invalid_output.write_text("not a directory", encoding="utf-8")
        result = self.run_cli("analyze", "--project", str(self.project), "--output", str(invalid_output), expect=1)
        self.assertEqual("FAILED", result["data_status"])
        self.assertEqual(before, output.joinpath("database-model.json").read_bytes())

    def test_query_without_save_creates_no_report_or_state(self) -> None:
        result = self.run_cli("query", "--project", str(self.project), "--object", "app_user")
        self.assertIn(result["data_status"], {"COMPLETE", "PARTIAL"})
        self.assertFalse((self.project / "reports").exists())
        self.assertFalse((self.project / "data").exists())

    def test_report_symlink_is_rejected_before_external_write(self) -> None:
        external = Path(self.temp.name) / "external"
        external.mkdir()
        os.symlink(external, self.project / "reports")
        result = self.run_cli("analyze", "--project", str(self.project), expect=1)
        self.assertEqual("FAILED", result["data_status"])
        self.assertIn("symbolic-link", " ".join(result["warnings"]))
        self.assertEqual([], list(external.iterdir()))

    def test_validation_rejects_duplicate_and_dangling_ids(self) -> None:
        model, _ = self.analyze()
        broken = copy.deepcopy(model)
        broken["databaseObjects"][0]["columns"][0]["id"] = broken["databaseObjects"][1]["columns"][0]["id"]
        broken["relationships"][0]["from"]["objectId"] = "missing"
        errors = validate_model(broken)
        self.assertTrue(any("duplicate id" in error for error in errors))
        self.assertTrue(any("missing from object" in error for error in errors))

    def test_conflicting_declared_targets_are_not_resolved_by_voting(self) -> None:
        migration = self.project / "src/main/resources/db/migration/V1__schema.sql"
        migration.write_text(
            migration.read_text(encoding="utf-8").replace(
                "CREATE TABLE app_user (",
                "CREATE TABLE company (id BIGINT PRIMARY KEY);\n\nCREATE TABLE app_user (",
            ).replace("REFERENCES department(id)", "REFERENCES company(id)"),
            encoding="utf-8",
        )
        model, output = self.analyze("--full-rescan")
        self.assertEqual("PARTIAL", model["analysisStatus"])
        self.assertTrue(any(c["kind"] == "RELATIONSHIP_TARGET_CONFLICT" for c in model["conflicts"]))
        self.assertTrue(all(r["status"] == "CONFLICTED" for r in model["relationships"] if r["from"]["columnIds"]))
        erd = output.joinpath("database-erd.mmd").read_text(encoding="utf-8")
        self.assertFalse(any(" : \"" in line for line in erd.splitlines()))

    def test_naming_candidate_is_reported_but_not_drawn_as_relation(self) -> None:
        migration = self.project / "src/main/resources/db/migration/V1__schema.sql"
        migration.write_text(
            "CREATE TABLE department (id BIGINT PRIMARY KEY);\n"
            "CREATE TABLE audit_log (id BIGINT PRIMARY KEY, department_id BIGINT);\n",
            encoding="utf-8",
        )
        for path in [
            self.project / "src/main/java/example/User.java",
            self.project / "src/main/java/example/Department.java",
            self.project / "src/main/java/example/UserMapper.java",
            self.project / "src/main/resources/mapper/UserMapper.xml",
        ]:
            path.unlink()
        model, output = self.analyze("--full-rescan")
        self.assertEqual(1, len(model["candidates"]))
        self.assertEqual("LOW", model["candidates"][0]["confidence"])
        self.assertNotIn("NAME?", output.joinpath("database-erd.mmd").read_text(encoding="utf-8"))
        self.assertFalse(any(line.startswith("Ref:") for line in output.joinpath("database.dbml").read_text(encoding="utf-8").splitlines()))

    def test_scoped_analysis_keeps_direct_neighbor_only(self) -> None:
        model, _ = self.analyze("--scope", "app_user")
        self.assertEqual({"app_user", "department"}, {o["name"] for o in model["databaseObjects"]})
        self.assertEqual("SCOPED", model["scope"]["mode"])

    def test_simple_java_string_concatenation_is_reconstructed(self) -> None:
        mapper = self.project / "src/main/java/example/UserMapper.java"
        mapper.write_text(
            "package example;\n"
            "class UserMapper {\n"
            "  String sql = \"SELECT u.id \" +\n"
            "      \"FROM app_user u JOIN department d \" +\n"
            "      \"ON u.dept_id = d.id\";\n"
            "}\n",
            encoding="utf-8",
        )
        model, _ = self.analyze("--full-rescan")
        relation = model["relationships"][0]
        self.assertIn("SQL_JOIN", relation["sourceTypes"])
        java_evidence = [e for e in model["evidence"] if e["file"].endswith("UserMapper.java") and e["sourceType"] == "JAVA_SQL"]
        self.assertTrue(java_evidence)
        self.assertTrue(all(e["startLine"] >= 3 for e in java_evidence))

    def test_flyway_alter_and_drop_restore_current_shape(self) -> None:
        migration_dir = self.project / "src/main/resources/db/migration"
        migration_dir.joinpath("V2__alter.sql").write_text(
            "ALTER TABLE app_user ADD COLUMN email VARCHAR(200);\n"
            "ALTER TABLE app_user DROP COLUMN username;\n",
            encoding="utf-8",
        )
        model, _ = self.analyze("--full-rescan")
        user = next(o for o in model["databaseObjects"] if o["name"] == "app_user")
        self.assertIn("email", {c["name"] for c in user["columns"]})
        self.assertNotIn("username", {c["name"] for c in user["columns"]})
        migration_dir.joinpath("V3__drop.sql").write_text("DROP TABLE app_user;\n", encoding="utf-8")
        self.project.joinpath("src/main/java/example/User.java").unlink()
        self.project.joinpath("src/main/java/example/UserMapper.java").unlink()
        self.project.joinpath("src/main/resources/mapper/UserMapper.xml").unlink()
        model, _ = self.analyze("--full-rescan")
        self.assertNotIn("app_user", {o["name"] for o in model["databaseObjects"]})


if __name__ == "__main__":
    unittest.main()
