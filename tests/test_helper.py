import importlib.util
import contextlib
import io
import json
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


class FakeEqualizer:
    def __init__(self, count=10):
        self.count = count
        self.gains = {'left': [0.0] * count, 'right': [0.0] * count}
        self.commands = []

    def request(self, command):
        self.commands.append(command)
        parts = command.split(':')
        if command == 'get_global_bypass':
            return '2'
        name = parts[-1] if parts[0] == 'get_property' else parts[-2]
        if name.startswith('band'):
            index = int(name[4:].split('Gain')[0].split('Frequency')[0])
            channel = parts[4]
            if parts[0] == 'set_property':
                self.gains[channel][index] = float(parts[-1])
                return None
            if name.endswith('Gain'):
                return str(self.gains[channel][index])
            return str(31 * 2 ** (index / 3))
        return str(self.count) if name == 'numBands' else 'false'


class GainBatchTests(unittest.TestCase):
    def run_action(self, engine, changes):
        output = io.StringIO()
        with patch.object(helper, 'request', side_effect=engine.request), \
                patch.object(helper, 'plugin_status', return_value=None), \
                patch.object(helper.shutil, 'which', return_value='/usr/bin/easyeffects'), \
                patch.object(helper.os.path, 'exists', return_value=True), \
                patch.object(helper.sys, 'argv', ['easyeffects.py', 'gains', json.dumps(changes)]), \
                contextlib.redirect_stdout(output):
            helper.main()
        return json.loads(output.getvalue())

    def test_single_edit_updates_only_that_band_on_both_channels(self):
        engine = FakeEqualizer()
        result = self.run_action(engine, {'3': 2.5})
        self.assertTrue(result['ready'])
        self.assertEqual(result['bands'][3]['gain'], 2.5)
        self.assertEqual(engine.gains['left'], [0, 0, 0, 2.5, 0, 0, 0, 0, 0, 0])
        self.assertEqual(engine.gains['right'], engine.gains['left'])
        writes = [c for c in engine.commands if c.startswith('set_property:')]
        self.assertEqual(len(writes), 2)
        self.assertTrue(all(':band3Gain:' in c for c in writes))
        # A ten-band slider edit previously used 88 socket requests.
        self.assertLessEqual(len(engine.commands), 29)

    def test_batch_preserves_other_bands_and_updates_stereo(self):
        engine = FakeEqualizer(32)
        engine.gains['left'][7] = -3
        engine.gains['right'][7] = 1
        result = self.run_action(engine, {'0': 4, '31': -2})
        self.assertTrue(result['ready'])
        for channel in ('left', 'right'):
            self.assertEqual(engine.gains[channel][0], 4)
            self.assertEqual(engine.gains[channel][31], -2)
        self.assertEqual(engine.gains['left'][7], -3)
        self.assertEqual(engine.gains['right'][7], 1)
        self.assertEqual(len([c for c in engine.commands if c.startswith('set_property:')]), 4)

    def test_invalid_batch_never_partially_writes(self):
        for changes in ({'0': 2, '10': 3}, {'0': 2, 'bad': 3}, {'0': 13},
                        {'0': float('nan')}, {'0': float('inf')}, {'0': True}, {}, []):
            with self.subTest(changes=changes):
                engine = FakeEqualizer()
                result = self.run_action(engine, changes)
                self.assertFalse(result['ready'])
                self.assertFalse(any(c.startswith('set_property:') for c in engine.commands))


if __name__ == '__main__':
    unittest.main()
