import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('helper', Path(__file__).resolve().parents[1] / 'assets/sound/easyeffects.py')
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


class SocketEncodingTests(unittest.TestCase):
    def test_bypass_is_sent_as_lowercase_boolean_and_verified(self):
        for value, returned in ((True, 'true'), (False, 'false')):
            with self.subTest(value=value), patch.object(helper, 'request', side_effect=[None, returned]) as request:
                helper.set_prop('bypass', value)
                self.assertEqual(request.call_args_list[0].args[0], 'set_property:output:equalizer:0:bypass:' + str(value).lower())

    def test_gain_write_keeps_channel_and_checks_readback(self):
        with patch.object(helper, 'request', side_effect=[None, '4.5']) as request:
            helper.set_prop('band0Gain', 4.5, 'left')
            self.assertEqual(request.call_args_list[0].args[0], 'set_property:output:equalizer:0:left:band0Gain:4.5')

    def test_rejected_write_is_reported(self):
        with patch.object(helper, 'request', side_effect=[None, 'false']):
            with self.assertRaisesRegex(ValueError, 'did not apply bypass'):
                helper.set_prop('bypass', True)


if __name__ == '__main__':
    unittest.main()
