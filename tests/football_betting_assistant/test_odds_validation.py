#!/usr/bin/env python3
"""Odds contract regressions, including CLI and snapshot report consumers."""
from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / 'football-betting-assistant' / 'scripts'
spec = importlib.util.spec_from_file_location('football_odds_validation_test', SCRIPTS / 'validate_inputs.py')
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)
BASE = dict(market='match_result', bookmaker_or_source='fixture', observed_at='2026-10-23T10:00:00+08:00', confidence='high', home_price=2.1)


class OddsValidationTests(unittest.TestCase):
    def test_invalid_fields_are_rejected_without_crashing(self):
        invalid = [
            {'home_price': value} for value in (-1, 0, 1, 'oops', True, False, [], {}, float('nan'), float('inf'))
        ] + [
            {'market': 'not_a_market'}, {'market': []}, {'confidence': {}},
            {'bookmaker_or_source': None}, {'bookmaker_or_source': 42},
            {'observed_at': 'yesterday'}, {'observed_at': '2026-10-23'}, {'observed_at': '2026-10-23T10:00:00'},
            {'line': True}, {'selections': None}, {'selections': {}},
            {'selections': [None]}, {'selections': [{}]}, {'selections': [{'name': 'win'}]},
            {'selections': [{'name': None, 'odds': 2}]}, {'selections': [{'name': 'win', 'odds': '2'}]},
            {'selections': [{'name': 'win', 'odds': True}]}, {'selections': [{'name': 'win', 'odds': 1}]},
            {'selections': [{'name': 'win', 'odds': 2, 'source_name': None}]},
            {'selections': [{'name': 'win', 'odds': 2, 'extra': 1}]}, {'extra': 'rejected'},
        ]
        for changes in invalid:
            with self.subTest(changes=changes):
                errors, _ = validator.validate_odds({**BASE, **changes}, 'data')
                self.assertTrue(errors)

    def test_missing_null_and_valid_values_have_distinct_outcomes(self):
        for field in validator.ODDS_SCHEMA['required']:
            missing = dict(BASE)
            del missing[field]
            errors, _ = validator.validate_odds(missing, 'data')
            self.assertTrue(any('missing required' in error for error in errors))
            errors, _ = validator.validate_odds({**BASE, field: None}, 'data')
            self.assertTrue(errors)
            self.assertFalse(any('missing required' in error for error in errors))
        for market in validator.ODDS_SCHEMA['properties']['market']['enum']:
            errors, _ = validator.validate_odds({**BASE, 'market': market, 'line': '-1', 'selections': [{'name': 'win', 'odds': None}]}, 'data')
            self.assertEqual(errors, [])
        errors, warnings = validator.validate_odds({**BASE, 'home_price': None, 'confidence': 'low'}, 'data')
        self.assertEqual(errors, [])
        self.assertTrue(any('no prices' in warning for warning in warnings))
        self.assertTrue(any('low odds confidence' in warning for warning in warnings))
        self.assertEqual(validator.validate_odds(BASE, 'data'), ([], []))

    def test_cli_stable_failures_for_bad_odds_and_malformed_documents(self):
        documents = [{'kind': 'odds', 'data': {**BASE, **change}} for change in ({'home_price': -1}, {'home_price': 'oops'}, {'market': 'not_a_market'})]
        documents += [[], {'kind': 'odds', 'data': []}, {'kind': ['odds'], 'data': {}}, {'kind': 'bundle', 'data': {'odds': [None]}}]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'input.json'
            for document in documents + ['invalid JSON']:
                path.write_text(document if isinstance(document, str) else json.dumps(document))
                for entry in ('validate_inputs.py', 'football_skill.py'):
                    args = ['validate'] if entry == 'football_skill.py' else []
                    result = subprocess.run([sys.executable, '-B', str(SCRIPTS / entry), *args, str(path)], text=True, capture_output=True)
                    payload = json.loads(result.stdout)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    if args:
                        self.assertEqual(payload['error_code'], 'DATA_VALIDATION_FAILED')
                        payload = payload['data']
                    self.assertFalse(payload['valid'])
                    self.assertTrue(payload['errors'])
                    self.assertNotIn('Traceback', result.stderr)

    def test_snapshot_selection_types_and_missing_odds_are_also_checked(self):
        snapshot = json.loads((ROOT / 'tests/fixtures/football_betting_assistant/football-snapshot-sporttery.json').read_text())
        for selection in (None, {}, {'name': 'win'}, {'name': 'win', 'odds': True}, {'name': 'win', 'odds': float('nan')}):
            data = copy.deepcopy(snapshot)
            data['data']['matches'][0]['markets'][0]['selections'] = [selection]
            with self.subTest(selection=selection):
                self.assertFalse(validator.validate_document(data)['valid'])

    def test_invalid_snapshot_cannot_generate_report_artifacts(self):
        snapshot = json.loads((ROOT / 'tests/fixtures/football_betting_assistant/football-snapshot-sporttery.json').read_text())
        snapshot['data']['matches'][0]['markets'][0]['selections'] = [{'name': 'win', 'odds': -1}]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'invalid.json'
            path.write_text(json.dumps(snapshot))
            out = Path(tmp) / 'reports'
            result = subprocess.run([sys.executable, str(SCRIPTS / 'football_skill.py'), 'report', str(path), '--report-out-dir', str(out)], text=True, capture_output=True)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(json.loads(result.stdout)['error_code'], 'DATA_VALIDATION_FAILED')
            self.assertFalse(out.exists())


class MatchModelCalculationTests(unittest.TestCase):
    def test_complete_model_and_missing_input_degradation(self):
        example = json.loads((ROOT / 'examples/football_betting_assistant/single-match-model-input.json').read_text())
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'model.json'
            for document, has_value in ((example, True), ({**example, 'odds': {}}, False)):
                path.write_text(json.dumps(document))
                result = subprocess.run([sys.executable, '-B', str(SCRIPTS / 'match_model_calculator.py'), str(path)], text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                payload = json.loads(result.stdout)
                self.assertEqual(payload['kind'], 'match_model_record')
                model = payload['model_record']
                probabilities = model['poisson']['result_probabilities']
                self.assertAlmostEqual(sum(probabilities.values()) + model['poisson']['tail_mass'], 1, places=10)
                self.assertEqual(model['grade']['value_judgment_available'], has_value)
                self.assertEqual(model['implied_probability'] is not None, has_value)
            path.write_text(json.dumps({'teams': {}}))
            result = subprocess.run([sys.executable, '-B', str(SCRIPTS / 'match_model_calculator.py'), str(path)], text=True, capture_output=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn('teams missing required fields', result.stderr)
            self.assertFalse(result.stdout.strip())
