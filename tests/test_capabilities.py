"""Capability evidence must not overstate validation or enable native execution."""

import unittest

from weskill.capabilities import capability_report


class CapabilityEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.report = capability_report()
        self.operations = {item['id']: item for item in self.report['capabilities']}

    def test_verified_core_operations_have_actual_native_evidence(self):
        for name in ('list_contacts', 'list_groups', 'get_messages', 'send_private_text',
                     'send_group_text', 'send_image', 'send_file'):
            with self.subTest(name=name):
                operation = self.operations[name]
                self.assertEqual(operation['status'], 'prototype_verified')
                self.assertEqual(operation['evidence'][0]['kind'], 'native_runtime_verified')
                self.assertNotIn('runtime_registered', [item['kind'] for item in operation['evidence']])

    def test_user_reports_remain_distinct_from_native_validation(self):
        for name in ('add_friend', 'accept_friend_request'):
            self.assertEqual(self.operations[name]['status'], 'user_reported')
            self.assertEqual(self.operations[name]['evidence'][0]['kind'], 'user_reported_validation')
        self.assertIn('user_reported', self.report['status_definitions'])

    def test_social_validation_does_not_claim_public_or_multi_image_tests(self):
        publication = self.operations['publish_moments']['evidence'][0]['limitation']
        self.assertIn('private/self', publication)
        self.assertIn('public and multi-image publication are not live-verified', publication)
        self.assertIn('saved PNG and searched GIF', self.operations['send_custom_sticker']['evidence'][0]['limitation'])

    def test_diagnostic_mode_and_realtime_remain_unavailable(self):
        self.assertEqual(self.report['available_tools'], ['get_client_identity', 'get_capabilities'])
        self.assertFalse(self.report['business_operations_available'])
        self.assertTrue(all(not item['execution_available'] for item in self.operations.values()))
        self.assertEqual(self.operations['receive_messages']['status'], 'unverified')
        self.assertEqual(self.operations['receive_messages']['evidence'], [])


if __name__ == '__main__':
    unittest.main()
