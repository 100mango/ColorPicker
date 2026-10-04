import unittest
import uuid
from watch_runtime_pair import phone_template, device_inventory, verify_pair, verify_new_device


class WatchPairTests(unittest.TestCase):
    def test_creation_must_not_return_a_default_or_previously_owned_uuid(self):
        default, owned, fresh = [str(uuid.uuid4()).upper() for _ in range(3)]
        original = {'any-installed-runtime': [{'udid': default}]}
        created = [{'udid': owned}]
        self.assertEqual(verify_new_device(fresh, original, created), fresh)
        for identifier in (default, default.lower(), owned, 'not-a-uuid'):
            with self.assertRaises(ValueError): verify_new_device(identifier, original, created)

    def test_selects_observed_installed_phone_type_without_altering_default_devices(self):
        phone = {'name':'iPhone SE (3rd generation)', 'udid':'template-phone', 'state':'Shutdown',
                 'isAvailable':True, 'deviceTypeIdentifier':'observed-phone-type'}
        devices = {'com.apple.CoreSimulator.SimRuntime.iOS-27-0':[phone],
                   'com.apple.CoreSimulator.SimRuntime.iOS-26-0':[dict(phone, name='iPhone older')],
                   'com.apple.CoreSimulator.SimRuntime.watchOS-27-0':[]}
        runtime, template = phone_template(devices)
        self.assertTrue(runtime.endswith('iOS-27-0')); self.assertEqual(template, phone)
        self.assertEqual(template['state'], 'Shutdown')
        self.assertEqual(len(device_inventory(devices)),1)

    def test_pair_must_match_both_exact_created_devices(self):
        value = {'pairs':{'created-pair':{'watch':{'udid':'owned-watch'}, 'phone':{'udid':'owned-phone'}}}}
        self.assertEqual(verify_pair(value,'created-pair','owned-watch','owned-phone'), value['pairs']['created-pair'])
        for pair, watch, phone in [('missing','owned-watch','owned-phone'),
                                   ('created-pair','default-watch','owned-phone'),
                                   ('created-pair','owned-watch','default-phone')]:
            with self.assertRaises(ValueError): verify_pair(value,pair,watch,phone)
        with self.assertRaises(ValueError): verify_pair({'pairs':[]},'created-pair','owned-watch','owned-phone')
        with self.assertRaises(ValueError):
            verify_pair(value,'created-pair','owned-watch','owned-phone',{'created-pair':{}})


if __name__=='__main__': unittest.main()
