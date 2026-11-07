import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('installer', ROOT / 'install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)
FIXTURE = (ROOT / 'tests/fixtures/Content.qml').read_text()


class NavigationTests(unittest.TestCase):
    def test_install_is_idempotent_and_preserves_other_tabs(self):
        updated = installer.patch_navigation(FIXTURE)
        self.assertEqual(installer.patch_navigation(updated), updated)
        self.assertEqual(updated.count('component: equalizerComponent'), 1)
        for tab in ('dashComponent', 'mediaComponent', 'performanceComponent', 'weatherComponent'):
            self.assertEqual(updated.count('component: ' + tab), 1)

    def test_uninstall_removes_only_equalizer(self):
        updated = installer.patch_navigation(FIXTURE)
        restored = installer.remove_navigation(updated)
        self.assertEqual(restored.split(), FIXTURE.split())

    def test_unknown_layout_is_rejected(self):
        with self.assertRaises(RuntimeError):
            installer.patch_navigation('Item { property string importantUserConfig: "keep" }')

    def test_customized_equalizer_is_not_removed(self):
        updated = installer.patch_navigation(FIXTURE).replace('EqualizerTab {}', 'EqualizerTab { custom: true }')
        with self.assertRaises(RuntimeError):
            installer.remove_navigation(updated)


class AudioSettingsTests(unittest.TestCase):
    def test_fresh_setup_creates_flat_stereo_ten_band_equalizer(self):
        main, eq, changed = installer.prepare_audio_config('', '')
        self.assertTrue(changed)
        self.assertEqual(installer.read_plugins(main), ['equalizer#0'])
        config = installer.configparser.ConfigParser(interpolation=None)
        config.optionxform = str
        config.read_string(eq)
        self.assertEqual(config['soe][Equalizer#0']['numBands'], '10')
        for channel in ('left', 'right'):
            settings = config[f'soe][Equalizer#0#{channel}']
            for i, frequency in enumerate(installer.FREQUENCIES):
                self.assertEqual(settings[f'band{i}Frequency'], str(frequency))
                self.assertEqual(settings[f'band{i}Gain'], '0')
                self.assertEqual(settings[f'band{i}Type'], '1')
            for i in range(10, 32):
                self.assertEqual(settings[f'band{i}Type'], '0')

    def test_existing_effects_and_input_chain_are_preserved(self):
        original = ('# keep this comment\n[StreamOutputs]\nplugins=compressor#0,limiter#0\n'
                    'blocklist=chat\n\n[StreamInputs]\nplugins=gate#0\noutputDevice=mydevice\n')
        eq_original = '[sie][Equalizer#0]\nnumBands=5\n'
        main, eq, changed = installer.prepare_audio_config(original, eq_original)
        self.assertTrue(changed)
        self.assertEqual(installer.read_plugins(main), ['compressor#0', 'limiter#0', 'equalizer#0'])
        self.assertIn('# keep this comment\n', main)
        self.assertIn('blocklist=chat\n', main)
        self.assertIn('[StreamInputs]\nplugins=gate#0\noutputDevice=mydevice\n', main)
        self.assertTrue(eq.startswith(eq_original))

    def test_existing_equalizer_is_untouched(self):
        main = '[StreamOutputs]\nplugins=equalizer#0,limiter#0\n'
        eq = '[soe][Equalizer#0]\nnumBands=32\ninputGain=-7.5\n'
        self.assertEqual(installer.prepare_audio_config(main, eq), (main, eq, False))

    def test_setup_is_idempotent(self):
        main, eq, _ = installer.prepare_audio_config('', '')
        self.assertEqual(installer.prepare_audio_config(main, eq), (main, eq, False))

    def test_different_equalizer_instance_is_preserved(self):
        main, _, _ = installer.prepare_audio_config('[StreamOutputs]\nplugins=equalizer#2\n', '')
        self.assertEqual(installer.read_plugins(main), ['equalizer#2', 'equalizer#0'])

    def test_setting_without_trailing_newline(self):
        text = installer.set_ini_values('[StreamOutputs]\nblocklist=chat', 'StreamOutputs', {'plugins': 'equalizer#0'})
        self.assertIn('blocklist=chat\nplugins=equalizer#0\n', text)


class AudioSetupTests(unittest.TestCase):
    def test_fresh_setup_keeps_chain_and_verifies_backend(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            db = base / 'easyeffects/db'
            db.mkdir(parents=True)
            backup = base / 'backup'
            backup.mkdir()
            main = db / 'easyeffectsrc'
            main.write_text('[StreamOutputs]\nplugins=compressor#0\n[StreamInputs]\nplugins=gate#0\n')
            helper = Mock()
            helper.prop.side_effect = [ValueError('error_plugin_not_found'), '10']
            helper.snapshot.return_value = {'ready': True, 'status': 'Equalizer available'}
            with patch.object(installer, 'helper_module', return_value=helper), \
                    patch.object(installer, 'stop_audio') as stop, \
                    patch.object(installer, 'start_audio') as start, \
                    patch.object(installer, 'wait_socket'):
                installer.setup_audio(base, backup)
            stop.assert_called_once_with(helper)
            start.assert_called_once()
            self.assertEqual(installer.read_plugins(main.read_text()), ['compressor#0', 'equalizer#0'])
            self.assertIn('plugins=gate#0', main.read_text())
            self.assertTrue((db / 'equalizerrc').is_file())
            self.assertIn('plugins=compressor#0', (backup / 'easyeffectsrc').read_text())

    def test_startup_failure_restores_original_audio_files(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            db = base / 'easyeffects/db'
            db.mkdir(parents=True)
            backup = base / 'backup'
            backup.mkdir()
            main = db / 'easyeffectsrc'
            original = '[StreamOutputs]\nplugins=limiter#0\n'
            main.write_text(original)
            helper = Mock()
            helper.prop.side_effect = ValueError('error_plugin_not_found')
            with patch.object(installer, 'helper_module', return_value=helper), \
                    patch.object(installer, 'stop_audio'), \
                    patch.object(installer, 'start_audio'), \
                    patch.object(installer, 'wait_socket', side_effect=[None, RuntimeError('startup failed')]):
                with self.assertRaisesRegex(RuntimeError, 'startup failed'):
                    installer.setup_audio(base, backup)
            self.assertEqual(main.read_text(), original)
            self.assertFalse((db / 'equalizerrc').exists())


class InstallationTests(unittest.TestCase):
    def test_install_reinstall_uninstall_in_isolated_home(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            config_home = base / 'config'
            data_home = base / 'data'
            shell = config_home / 'quickshell/caelestia'
            dashboard = shell / 'modules/dashboard'
            dashboard.mkdir(parents=True)
            (shell / 'shell.qml').write_text('import Quickshell\nShellRoot {}\n')
            (dashboard / 'Content.qml').write_text(FIXTURE)
            env = {'XDG_CONFIG_HOME': str(config_home), 'XDG_DATA_HOME': str(data_home)}
            with patch.dict(installer.os.environ, env), patch.object(installer, 'verify_easyeffects'), \
                    patch.object(installer.shutil, 'which', return_value='/usr/bin/qs'), \
                    patch.object(installer.os, 'geteuid', return_value=1000):
                args = ['--no-packages', '--no-audio-setup', '--no-autostart', '--no-restart']
                installer.main(args)
                self.assertTrue((dashboard / 'EqualizerTab.qml').is_file())
                self.assertTrue((dashboard / 'sound/easyeffects.py').is_file())
                first = (dashboard / 'Content.qml').read_text()
                installer.main(args)
                self.assertEqual((dashboard / 'Content.qml').read_text(), first)
                preset = data_home / 'easyeffects/output/Caelestia Equalizer.json'
                self.assertEqual(json.loads(preset.read_text())['output']['equalizer#0']['num-bands'], 10)
                installer.main(['--uninstall', '--no-restart'])
                self.assertFalse((dashboard / 'EqualizerTab.qml').exists())
                self.assertEqual((dashboard / 'Content.qml').read_text().split(), FIXTURE.split())
                self.assertTrue(preset.is_file())

    def test_failed_atomic_write_keeps_original_and_cleans_temporary_file(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'settings'
            installer.atomic_write(path, 'first')
            with patch.object(installer.os, 'replace', side_effect=OSError('read-only')):
                with self.assertRaises(OSError):
                    installer.atomic_write(path, 'second')
            self.assertEqual(path.read_text(), 'first')
            self.assertEqual(list(path.parent.iterdir()), [path])


if __name__ == '__main__':
    unittest.main()
