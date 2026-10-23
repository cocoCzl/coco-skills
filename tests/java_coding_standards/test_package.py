"""Package invariants, not claims about model selection or coding behavior."""

import hashlib
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from scripts.check_all_skills import check_interface_contract, discover_skills


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "java-coding-standards"


def normalized(element):
    return (element.tag, sorted(element.attrib.items()), (element.text or "").strip(),
            [normalized(child) for child in element])


class PackageTests(unittest.TestCase):
    def test_java_asset_preserves_source_projection(self):
        root = ET.parse(SKILL / "assets/java-code-style.xml").getroot()
        # Digest of original global options + JAVA subtree, excluding serialization whitespace.
        digest = hashlib.sha256(repr(normalized(root)).encode()).hexdigest()
        self.assertEqual(digest, "56dbb841b71ad5b774c3220645228b302670a9d2225248a59701996dce25aab3")
        self.assertEqual([node.get("language") for node in root.findall("codeStyleSettings")], ["JAVA"])
        self.assertEqual(root.find("option[@name='RIGHT_MARGIN']").get("value"), "100")
        java = root.find("codeStyleSettings[@language='JAVA']")
        for key in ("INDENT_SIZE", "CONTINUATION_INDENT_SIZE", "TAB_SIZE"):
            self.assertEqual(java.find("indentOptions/option[@name='%s']" % key).get("value"), "4")
        self.assertIsNone(java.find("option[@name='RIGHT_MARGIN']"))

    def test_package_contains_only_installable_guidance_and_asset(self):
        files = list(SKILL.rglob("*"))
        allowed = {".md", ".xml", ".yaml"}
        self.assertTrue(all(p.suffix in allowed for p in files if p.is_file()))
        for path in files:
            if path.is_file():
                self.assertNotIn("/Users/", path.read_text(), str(path))
        self.assertFalse((SKILL / "scripts").exists())
        self.assertFalse((SKILL / "schemas").exists())
        self.assertEqual(check_interface_contract(SKILL), [])

    def test_all_existing_machine_skills_still_require_schema(self):
        for skill in discover_skills():
            if skill.name == SKILL.name:
                continue
            with self.subTest(skill=skill.name), tempfile.TemporaryDirectory() as tmp:
                # Merely removing scripts/schema never grants guidance status.
                missing = Path(tmp) / skill.name
                missing.mkdir()
                self.assertTrue(check_interface_contract(missing))
                self.assertEqual(check_interface_contract(skill), [])

    def test_new_unclassified_skill_cannot_skip_interface_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = Path(tmp) / "new-skill"
            skill.mkdir()
            self.assertTrue(check_interface_contract(skill))
            (skill / "schemas").mkdir()
            schema = skill / "schemas/agent-result.schema.json"
            for invalid in ({"required": ["status"]}, [], {"required": [{}]}):
                schema.write_text(json.dumps(invalid))
                self.assertTrue(check_interface_contract(skill))
            schema.write_text("not json")
            self.assertTrue(check_interface_contract(skill))

    def test_guidance_cannot_grow_unchecked_machine_interface(self):
        for directory in ("scripts", "schemas"):
            with self.subTest(directory=directory), tempfile.TemporaryDirectory() as tmp:
                skill = Path(tmp) / SKILL.name
                (skill / directory).mkdir(parents=True)
                self.assertTrue(check_interface_contract(skill))


if __name__ == "__main__":
    unittest.main()
