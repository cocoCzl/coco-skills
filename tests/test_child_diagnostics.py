#!/usr/bin/env python3
"""Exercise both independently installable wrappers at their subprocess boundary."""
from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class ChildDiagnosticsTests(unittest.TestCase):
    def wrappers(self):
        for directory, filename in (("ai-resume-expert", "resume_skill.py"), ("football-betting-assistant", "football_skill.py")):
            entry = ROOT / directory / "scripts" / filename
            spec = importlib.util.spec_from_file_location(directory.replace('-', '_') + '_entry_test', entry)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            yield entry, module

    def invoke(self, entry, module, code, stdout, stderr):
        stream = io.StringIO()
        process = subprocess.CompletedProcess([], code, stdout, stderr)
        with patch.object(module.sys, 'argv', [str(entry), 'validate', 'input.json']), patch.object(module.subprocess, 'run', return_value=process), redirect_stdout(stream):
            result = module.main()
        return result, json.loads(stream.getvalue())

    def test_valid_json_preserves_warnings_and_logs_without_failing(self):
        for entry, module in self.wrappers():
            with self.subTest(skill=entry):
                code, payload = self.invoke(entry, module, 0, '{"valid": true}', 'INFO cache reused\nwarning: optional tool unavailable')
                self.assertEqual(code, 0)
                self.assertEqual(payload['status'], 'completed')
                self.assertEqual(payload['warnings'], ['warning: optional tool unavailable'])
                self.assertEqual([d['level'] for d in payload['data']['child_diagnostics']], ['log', 'warning'])

    def test_structured_error_deduplicates_stderr_and_preserves_failure(self):
        for entry, module in self.wrappers():
            with self.subTest(skill=entry):
                code, payload = self.invoke(entry, module, 2, '{"error": {"code": "BAD_INPUT", "message": "bad input"}}', 'bad input\nextra failure details')
                self.assertEqual(code, 2)
                self.assertEqual(payload['error_code'], 'BAD_INPUT')
                self.assertEqual(payload['status'], 'blocked')
                self.assertTrue(payload['next_action'])
                self.assertEqual(payload['warnings'], [])
                self.assertEqual(payload['data']['child_diagnostics'], [{'level': 'error', 'message': 'extra failure details'}])

    def test_bad_or_empty_stdout_is_never_success_even_if_stderr_is_json(self):
        for entry, module in self.wrappers():
            for code, stdout, stderr in ((0, 'not JSON', 'diagnostic'), (0, '', ''), (0, '', '{"valid":true}'), (0, '[]', ''), (7, 'failed', 'reason'), (2, '{}', 'reason')):
                with self.subTest(skill=entry, code=code, stdout=stdout):
                    actual_code, payload = self.invoke(entry, module, code, stdout, stderr)
                    self.assertNotEqual(actual_code, 0)
                    self.assertEqual(payload['status'], 'blocked')
                    self.assertTrue(payload['next_action'])
                    if stdout != '{}':
                        self.assertEqual(payload['error_code'], 'INVALID_CHILD_OUTPUT')
                    if stderr:
                        self.assertIn(stderr, [item['message'] for item in payload['data']['child_diagnostics']])

    def test_capability_degradation_keeps_next_step_and_diagnostic(self):
        for entry, module in self.wrappers():
            with self.subTest(skill=entry):
                code, payload = self.invoke(entry, module, 3, '{}', 'tool missing')
                self.assertEqual(code, 3)
                self.assertTrue(payload['next_action'])
                self.assertIn('tool missing', json.dumps(payload))

    def test_spawn_failure_is_structured(self):
        for entry, module in self.wrappers():
            with self.subTest(skill=entry), patch.object(module.subprocess, 'run', side_effect=OSError('cannot spawn')):
                code, payload, stderr = module.run_child('missing.py', [])
                self.assertEqual(code, 2)
                self.assertEqual(payload['error']['message'], 'cannot spawn')
                self.assertEqual(stderr, '')

    def test_report_retains_nested_diagnostics_and_skips_audit_on_invalid_prediction(self):
        for entry, module in self.wrappers():
            if module.SKILL != 'football-betting-assistant':
                continue
            for validation_code in (0, 1):
                with self.subTest(validation_code=validation_code):
                    responses = [
                        (0, {'prediction_snapshot_path': 'prediction.json', 'data_status': 'usable-but-downgraded'}, 'builder warning'),
                        (validation_code, {'valid': not validation_code, 'errors': ['invalid prediction'] if validation_code else []}, 'validation details'),
                        (0, {'summary': {'main_plan_allowed': True}}, 'INFO audit done'),
                    ]
                    captured = io.StringIO()
                    with patch.object(module, 'run_child', side_effect=responses) as child, patch.object(module.sys, 'argv', [str(entry), 'report', 'snapshot.json']), redirect_stdout(captured):
                        code = module.main()
                    payload = json.loads(captured.getvalue())
                    self.assertEqual(code, validation_code)
                    self.assertEqual(child.call_count, 2 if validation_code else 3)
                    self.assertIn('validation details', [item['message'] for item in payload['data']['validation']['child_diagnostics']])
                    if validation_code:
                        self.assertNotIn('risk_audit', payload['data'])
                    else:
                        self.assertEqual(payload['data']['risk_audit']['child_diagnostics'][0]['level'], 'log')
