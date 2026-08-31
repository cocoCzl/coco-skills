#!/usr/bin/env python3
"""Release structure and behavior-matrix contracts for ai-resume-expert."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "ai-resume-expert"
EXAMPLES = ROOT / "examples" / "ai_resume_expert"
EVALS = ROOT / "evals" / "ai_resume_expert" / "evals.json"
TRIGGER_EVALS = ROOT / "evals" / "ai_resume_expert" / "trigger-evals.json"


class SkillReleaseContractTests(unittest.TestCase):
    def test_installable_entry_and_human_readme_exist(self) -> None:
        self.assertTrue((SKILL / "SKILL.md").is_file())
        self.assertTrue((SKILL / "README.md").is_file())
        root_readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("ai-resume-expert", root_readme)

    def test_frontmatter_name_and_trigger_description_are_complete(self) -> None:
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertLessEqual(len(text.splitlines()), 500)
        self.assertRegex(text, r"(?m)^name:\s*ai-resume-expert\s*$")
        description = re.search(r"(?m)^description:\s*(.+)$", text)
        self.assertIsNotNone(description)
        for intent in ("生成简历", "诊断", "代码库", "JD", "PDF", "ATS"):
            with self.subTest(intent=intent):
                self.assertIn(intent, description.group(1))

    def test_reference_index_routes_to_existing_files(self) -> None:
        index = SKILL / "references" / "index.md"
        self.assertTrue(index.is_file())
        index_text = index.read_text(encoding="utf-8")
        links = re.findall(r"\[[^\]]+\]\(([^)#]+\.md)(?:#[^)]+)?\)", index_text)
        self.assertGreaterEqual(len(links), 10)
        for relative in links:
            with self.subTest(relative=relative):
                self.assertTrue((index.parent / relative).resolve().is_file())

    def test_all_first_release_role_strategies_are_bundled(self) -> None:
        expected = {
            "backend.md",
            "frontend.md",
            "fullstack.md",
            "client-mobile.md",
            "test-development.md",
            "devops-sre-cloud-platform.md",
            "data-engineering.md",
            "algorithm-ml.md",
            "ai-llm.md",
            "tech-lead-architect.md",
        }
        actual = {path.name for path in (SKILL / "references" / "roles").glob("*.md")}
        self.assertTrue(expected.issubset(actual), expected - actual)

    def test_runtime_tools_and_schemas_are_bundled(self) -> None:
        scripts = {
            "scan_repository.py",
            "extract_resume.py",
            "validate_resume_package.py",
            "career_store.py",
            "render_resume.py",
            "validate_pdf.py",
            "record_pdf_visual_signoff.py",
        }
        for name in scripts:
            with self.subTest(name=name):
                self.assertTrue((SKILL / "scripts" / name).is_file())
        schemas = list((SKILL / "schemas").glob("*.schema.json"))
        self.assertGreaterEqual(len(schemas), 2)
        for path in schemas:
            json.loads(path.read_text(encoding="utf-8"))

    def test_behavior_eval_matrix_is_large_unique_and_role_complete(self) -> None:
        payload = json.loads(EVALS.read_text(encoding="utf-8"))
        self.assertEqual(payload["skill_name"], "ai-resume-expert")
        evals = payload["evals"]
        self.assertGreaterEqual(len(evals), 30)
        ids = [item["id"] for item in evals]
        self.assertEqual(len(ids), len(set(ids)))
        corpus = "\n".join(item["prompt"] + "\n" + item["expected_output"] for item in evals)
        for keyword in (
            "后端",
            "前端",
            "全栈",
            "Android",
            "测试开发",
            "SRE",
            "平台工程师",
            "数据工程师",
            "机器学习",
            "大模型",
            "技术负责人",
        ):
            with self.subTest(keyword=keyword):
                self.assertIn(keyword, corpus)
        for item in evals:
            with self.subTest(eval_id=item["id"]):
                self.assertTrue(item["prompt"].strip())
                self.assertTrue(item["expected_output"].strip())
                self.assertGreaterEqual(len(item.get("expectations", [])), 3)
                for relative in item.get("files", []):
                    self.assertTrue((ROOT / relative).is_file(), relative)

    def test_trigger_precision_eval_set_covers_nearby_out_of_scope_requests(self) -> None:
        payload = json.loads(TRIGGER_EVALS.read_text(encoding="utf-8"))
        self.assertEqual(payload["skill_name"], "ai-resume-expert")
        queries = payload["queries"]
        self.assertGreaterEqual(len(queries), 20)
        ids = [item["id"] for item in queries]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(any(item.get("should_trigger") is True for item in queries))
        self.assertTrue(any(item.get("should_trigger") is False for item in queries))
        for item in queries:
            with self.subTest(eval_id=item["id"]):
                self.assertTrue(item["query"].strip())
                self.assertTrue(item["reason"].strip())
                self.assertIsInstance(item["should_trigger"], bool)

    def test_every_role_strategy_has_jd_customization_behavior_coverage(self) -> None:
        evals = json.loads(EVALS.read_text(encoding="utf-8"))["evals"]
        jd_corpus = "\n".join(
            item["prompt"] + "\n" + item["expected_output"]
            for item in evals
            if "JD" in item["prompt"]
        )
        for keyword in (
            "Java 高级后端",
            "高级前端",
            "全栈工程师",
            "Android 高级",
            "测试开发",
            "SRE",
            "平台工程师",
            "数据工程师",
            "机器学习工程师",
            "LLM 应用工程师",
            "后端技术负责人",
        ):
            with self.subTest(keyword=keyword):
                self.assertIn(keyword, jd_corpus)

    def test_examples_are_repository_level_and_fictional(self) -> None:
        names = {path.name for path in EXAMPLES.glob("*.md")}
        self.assertTrue(
            {
                "direct-backend-profile.md",
                "backend-jd.md",
                "legacy-resume.md",
                "sample-resume.md",
                "prompts.md",
            }.issubset(names)
        )
        corpus = "\n".join(path.read_text(encoding="utf-8") for path in EXAMPLES.glob("*.md"))
        self.assertIn("虚构", corpus)
        self.assertNotIn("/Users/", corpus)
        self.assertNotRegex(corpus, r"(?i)(api[_-]?key|password|token)\s*[:=]\s*[^\s<{]+")

    def test_skill_declares_evidence_privacy_and_pdf_gates(self) -> None:
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        for phrase in (
            "代码和文档只能证明项目事实",
            "每轮只问当前最影响质量的一个问题",
            "最低证据门槛",
            "没有用户明确确认 Markdown 时，不生成最终 PDF",
            "有限降级",
            "职业证据库",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_macos_pdf_guidance_uses_scoped_outer_command_escalation(self) -> None:
        skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        readme = (SKILL / "README.md").read_text(encoding="utf-8")
        for text in (skill, readme):
            with self.subTest(source=text[:40]):
                self.assertIn("resume_skill.py render", text)
                self.assertIn("沙箱外", text)
                self.assertIn("不要关闭整个 Codex 沙箱", text)
        self.assertIn("Abort trap: 6", readme)
        self.assertIn("退出码 `134`", readme)

    def test_experienced_candidate_structure_requires_separate_star_sections(self) -> None:
        skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        rules = (SKILL / "references" / "common-resume-rules.md").read_text(encoding="utf-8")
        gates = (SKILL / "references" / "output-and-quality-gates.md").read_text(encoding="utf-8")
        for text in (skill, rules, gates):
            with self.subTest(source=text[:40]):
                self.assertIn("重点项目经历", text)
                self.assertIn("STAR", text)
        self.assertIn("默认独立设置**工作经历**与**重点项目经历**两章", skill)
        self.assertIn("每段保留任职默认写 2～4 条", skill)
        self.assertIn("首次交付必须", skill)

    def test_senior_backend_example_uses_separate_sections_and_no_usage_notes(self) -> None:
        sample = (EXAMPLES / "sample-resume.md").read_text(encoding="utf-8")
        self.assertIn("## 工作经历", sample)
        self.assertIn("## 重点项目经历", sample)
        self.assertLess(sample.index("## 工作经历"), sample.index("## 重点项目经历"))
        self.assertIn("｜星河软件（虚构）｜2023.03—至今", sample)
        self.assertNotIn("使用说明（不属于简历正文）", sample)


if __name__ == "__main__":
    unittest.main()
