#!/usr/bin/env python3
"""Install the Caelestia Equalizer dashboard tab and set up native EasyEffects."""

import argparse
import configparser
from datetime import datetime
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
MIN_EASYEFFECTS = (8, 3, 0)
FREQUENCIES = [31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]


def command(*args, check=True):
    return subprocess.run(args, text=True, capture_output=True, check=check, timeout=30)


def atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp = tempfile.mkstemp(prefix=f'.{path.name}.', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w') as handle:
            handle.write(text)
        if path.exists():
            os.chmod(temp, path.stat().st_mode & 0o777)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def require_dependencies(skip_packages):
    if not shutil.which('qs'):
        raise RuntimeError('Caelestia and Quickshell (qs) must already be installed.')
    if not shutil.which('pacman'):
        raise RuntimeError('Automatic package installation supports Arch Linux and CachyOS. '
                           'On other distributions, install native EasyEffects >= 8.3.0 and '
                           'LSP LV2 plugins, then use --no-packages.')
    packages = [name for name in ('easyeffects', 'lsp-plugins-lv2')
                if command('pacman', '-Q', name, check=False).returncode != 0]
    if packages and not skip_packages:
        print('Installing required packages:', ', '.join(packages), flush=True)
        subprocess.run(['sudo', 'pacman', '-S', '--needed', *packages], check=True)
    verify_easyeffects()


def verify_easyeffects():
    if not shutil.which('easyeffects'):
        raise RuntimeError('EasyEffects is missing. Install the native easyeffects package.')
    version = command('easyeffects', '--version')
    match = re.search(r'(\d+)\.(\d+)\.(\d+)', version.stdout + version.stderr)
    if not match or tuple(map(int, match.groups())) < MIN_EASYEFFECTS:
        raise RuntimeError('EasyEffects >= 8.3.0 is required for the local per-band control API. '
                           'Update your system packages and run the installer again.')


NAV_ENTRY = '''            {
                component: equalizerComponent,
                iconName: "equalizer",
                text: qsTr("Equalizer"),
                enabled: true
            },'''


def patch_navigation(original):
    if 'component: equalizerComponent' in original:
        if not re.search(r'id:\s*equalizerComponent\s+EqualizerTab\s*\{\s*\}', original):
            raise RuntimeError('Existing Equalizer navigation has an unexpected structure.')
        return original
    if 'component: soundComponent' in original:
        raise RuntimeError('An earlier Sound tab is present. Migrate it before installing.')
    media = re.compile(
        r'(?P<block>\{\s*component:\s*mediaComponent,\s*iconName:\s*"queue_music",'
        r'\s*text:\s*(?:Tr\.tr|qsTr)\("Media"\),\s*enabled:\s*Config\.dashboard\.showMedia\s*\},)')
    updated, count = media.subn(lambda m: m.group('block') + '\n' + NAV_ENTRY, original, count=1)
    if count != 1:
        raise RuntimeError('Unsupported Caelestia dashboard: could not find the Media navigation entry. '
                           'No dashboard files were changed.')
    performance = re.compile(r'(?P<indent>^[ \t]*)Component\s*\{\s*id:\s*performanceComponent', re.M)
    updated, count = performance.subn(
        lambda m: m.group('indent') + 'Component {\n'
        + m.group('indent') + '    id: equalizerComponent\n\n'
        + m.group('indent') + '    EqualizerTab {}\n'
        + m.group('indent') + '}\n\n' + m.group(0), updated, count=1)
    if count != 1:
        raise RuntimeError('Unsupported Caelestia dashboard: could not find page components. '
                           'No dashboard files were changed.')
    return updated


def remove_navigation(original):
    if 'component: equalizerComponent' not in original:
        return original
    entry = re.compile(r'^[ \t]*\{\s*component:\s*equalizerComponent,\s*iconName:\s*"equalizer",'
                       r'\s*text:\s*qsTr\("Equalizer"\),\s*enabled:\s*true\s*\},\n?', re.M)
    updated, entries = entry.subn('', original, count=1)
    component = re.compile(r'^[ \t]*Component\s*\{\s*id:\s*equalizerComponent\s*'
                           r'EqualizerTab\s*\{\s*\}\s*\}\n?', re.M)
    updated, components = component.subn('', updated, count=1)
    if entries != 1 or components != 1:
        raise RuntimeError('Equalizer navigation was customized; refusing to remove unrelated code.')
    return updated


def set_ini_values(text, section, values):
    """Change only specified keys; retain other settings, comments and KDE groups."""
    header = f'[{section}]'
    lines = text.splitlines(keepends=True)
    start = next((i for i, line in enumerate(lines) if line.strip() == header), None)
    if start is None:
        return text.rstrip() + '\n\n' + header + '\n' + ''.join(f'{k}={v}\n' for k, v in values.items())
    end = next((i for i in range(start + 1, len(lines)) if re.match(r'^\[.*\]\s*$', lines[i])), len(lines))
    remaining = dict(values)
    for i in range(start + 1, end):
        key = lines[i].split('=', 1)[0].strip() if '=' in lines[i] else None
        if key in remaining:
            lines[i] = f'{key}={remaining.pop(key)}\n'
    # Ensure a file with no final newline remains valid when adding a setting.
    if end and not lines[end - 1].endswith('\n'):
        lines[end - 1] += '\n'
    lines[end:end] = [f'{k}={v}\n' for k, v in remaining.items()]
    return ''.join(lines)


def read_plugins(text):
    config = configparser.ConfigParser(interpolation=None, strict=False)
    config.optionxform = str
    config.read_string(text)
    return [item.strip() for item in config.get('StreamOutputs', 'plugins', fallback='').split(',') if item.strip()]


def prepare_audio_config(main_text, eq_text):
    plugins = read_plugins(main_text)
    if 'equalizer#0' in plugins:
        return main_text, eq_text, False
    main_text = set_ini_values(main_text, 'StreamOutputs', {'plugins': ','.join([*plugins, 'equalizer#0'])})
    eq_text = set_ini_values(eq_text, 'soe][Equalizer#0', {
        'numBands': 10, 'bypass': 'false', 'inputGain': 0, 'outputGain': 0, 'splitChannels': 'false'})
    for channel in ('left', 'right'):
        values = {}
        for i in range(32):
            values[f'band{i}Type'] = 1 if i < 10 else 0
            values[f'band{i}Gain'] = 0
            if i < 10:
                values.update({f'band{i}Frequency': FREQUENCIES[i], f'band{i}Q': 1.41,
                               f'band{i}Mode': 0, f'band{i}Slope': 0,
                               f'band{i}Solo': 'false', f'band{i}Mute': 'false'})
        eq_text = set_ini_values(eq_text, f'soe][Equalizer#0#{channel}', values)
    return main_text, eq_text, True


def helper_module():
    spec = importlib.util.spec_from_file_location('equalizer_helper', HERE / 'assets/sound/easyeffects.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def systemd_available():
    return shutil.which('systemctl') and command('systemctl', '--user', 'show-environment', check=False).returncode == 0


def unit_installed():
    if not systemd_available():
        return False
    return command('systemctl', '--user', 'show', 'easyeffects.service', '-p', 'LoadState', '--value', check=False).stdout.strip() == 'loaded'


def start_audio():
    if unit_installed():
        command('systemctl', '--user', 'start', 'easyeffects.service')
    else:
        state = Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state')) / 'caelestia-equalizer'
        state.mkdir(parents=True, exist_ok=True)
        with (state / 'easyeffects.log').open('a') as log:
            subprocess.Popen(['easyeffects', '--service-mode', '--hide-window'], stdout=log, stderr=log, start_new_session=True)


def wait_socket(helper, available=True):
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        try:
            helper.request('get_global_bypass')
            alive = True
        except (OSError, ValueError):
            alive = False
        if alive == available:
            return
        time.sleep(0.2)
    raise RuntimeError('Timed out waiting for EasyEffects to ' + ('start. See ~/.local/state/caelestia-equalizer/easyeffects.log.' if available else 'stop.'))


def stop_audio(helper):
    if unit_installed() and command('systemctl', '--user', 'is-active', '--quiet', 'easyeffects.service', check=False).returncode == 0:
        command('systemctl', '--user', 'stop', 'easyeffects.service')
    else:
        command('easyeffects', '--quit', check=False)
    wait_socket(helper, False)
    # Allow the settings database to finish flushing after the socket closes.
    time.sleep(0.3)


def setup_audio(config_home, backup_dir):
    helper = helper_module()
    try:
        helper.request('get_global_bypass')
    except (OSError, ValueError):
        start_audio()
    wait_socket(helper)
    try:
        helper.prop('numBands')
        existing = True
    except ValueError as error:
        if str(error) != 'error_plugin_not_found':
            raise
        existing = False
    if not existing:
        print('Adding a flat ten-band output equalizer; keeping the existing effects chain.', flush=True)
        stop_audio(helper)
        paths = [config_home / 'easyeffects/db/easyeffectsrc', config_home / 'easyeffects/db/equalizerrc']
        originals = [path.read_text() if path.exists() else None for path in paths]
        for path in paths:
            if path.exists():
                shutil.copy2(path, backup_dir / path.name)
        try:
            main_text, eq_text, changed = prepare_audio_config(*(text or '' for text in originals))
            if changed:
                atomic_write(paths[0], main_text)
                atomic_write(paths[1], eq_text)
            start_audio()
            wait_socket(helper)
            if int(helper.prop('numBands')) < 1:
                raise RuntimeError('EasyEffects did not create the equalizer.')
        except Exception:
            # Restore the previous audio configuration if initialization fails.
            try:
                stop_audio(helper)
            except (OSError, RuntimeError, subprocess.SubprocessError):
                pass
            for path, original in zip(paths, originals):
                if original is None:
                    path.unlink(missing_ok=True)
                else:
                    atomic_write(path, original)
            start_audio()
            raise
    else:
        print('Keeping existing output equalizer settings.')
    result = helper.snapshot()
    if not result.get('ready') and 'not loaded' in result.get('status', ''):
        print('Restarting EasyEffects to load the newly installed LV2 plugin.', flush=True)
        stop_audio(helper)
        start_audio()
        wait_socket(helper)
        result = helper.snapshot()
    if not result.get('ready'):
        raise RuntimeError(result.get('status', 'Could not verify the equalizer.'))
    print('EasyEffects verified:', result['status'])
    if result.get('globalBypass') or result.get('bypass'):
        print('Existing bypass is enabled. Turn it off when you want to hear the equalizer.')


def setup_autostart(config_home, backup_dir):
    if systemd_available():
        if not unit_installed():
            unit = config_home / 'systemd/user/easyeffects.service'
            executable = shutil.which('easyeffects')
            if unit.exists():
                shutil.copy2(unit, backup_dir / 'easyeffects.service')
            atomic_write(unit, '[Unit]\nDescription=EasyEffects Audio Effects\n'
                         'After=pipewire.service wireplumber.service\n\n[Service]\nType=simple\n'
                         f'ExecStart="{executable}" --service-mode --hide-window\n'
                         'Restart=on-failure\nRestartSec=3\n\n[Install]\nWantedBy=default.target\n')
            command('systemctl', '--user', 'daemon-reload')
        command('systemctl', '--user', 'enable', 'easyeffects.service')
        print('EasyEffects will start automatically with the user session (systemd).')
    else:
        desktop = config_home / 'autostart/com.github.wwmm.easyeffects.desktop'
        if desktop.exists():
            shutil.copy2(desktop, backup_dir / 'easyeffects-autostart.desktop')
        atomic_write(desktop, '[Desktop Entry]\nType=Application\nName=EasyEffects\n'
                     'Exec=easyeffects --service-mode --hide-window\nTerminal=false\n'
                     'X-GNOME-Autostart-enabled=true\n')
        print('EasyEffects will start automatically with the desktop session (XDG autostart).')


def install_preset(data_home):
    preset_path = data_home / 'easyeffects/output/Caelestia Equalizer.json'
    if preset_path.exists():
        print('Keeping existing optional preset:', preset_path)
        return
    bands = {f'band{i}': {'frequency': float(f), 'gain': 0.0, 'q': 1.41, 'width': 4.0,
                          'type': 'Bell', 'mode': 'RLC (BT)', 'slope': 'x1', 'solo': False, 'mute': False}
             for i, f in enumerate(FREQUENCIES)}
    equalizer = {'bypass': False, 'input-gain': 0.0, 'output-gain': 0.0, 'num-bands': 10,
                 'mode': 'IIR', 'decramp': 'Off', 'split-channels': False, 'balance': 0.0,
                 'pitch-left': 0.0, 'pitch-right': 0.0, 'left': bands, 'right': bands}
    atomic_write(preset_path, json.dumps({'output': {'plugins_order': ['equalizer#0'],
                 'blocklist': [], 'equalizer#0': equalizer}}, indent=2) + '\n')
    print('Created optional flat preset:', preset_path)


def reload_shell(shell_dir):
    if 'Instance ' not in command('qs', '-p', str(shell_dir), 'list', check=False).stdout:
        print('Caelestia is not running; the tab will appear on its next start.')
        return
    result = command('qs', '-p', str(shell_dir), 'ipc', 'call', 'appearance', 'reloadShell', check=False)
    if result.returncode == 0:
        print('Caelestia configuration reloaded.')
        return
    command('qs', '-p', str(shell_dir), 'kill')
    for _ in range(50):
        if 'Instance ' not in command('qs', '-p', str(shell_dir), 'list', check=False).stdout:
            break
        time.sleep(0.1)
    command('qs', '-p', str(shell_dir), '-n', '-d')
    print('Caelestia restarted.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-packages', action='store_true', help='Use manually installed dependencies')
    parser.add_argument('--no-restart', action='store_true', help='Do not reload/restart the Caelestia shell')
    parser.add_argument('--no-audio-setup', action='store_true', help='Do not start or configure EasyEffects')
    parser.add_argument('--no-autostart', action='store_true', help='Do not enable EasyEffects at login')
    parser.add_argument('--uninstall', action='store_true', help='Remove the dashboard tab; keep audio settings and packages')
    parser.add_argument('--shell-dir', type=Path, help='Path to the existing Caelestia Quickshell configuration')
    args = parser.parse_args(argv)
    if os.geteuid() == 0:
        raise RuntimeError('Run ./install.sh as your normal desktop user, not with sudo. '
                           'Only package installation uses sudo.')
    config_home = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config'))
    data_home = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share'))
    shell_dir = (args.shell_dir or Path(os.environ.get('CAELESTIA_DIR', config_home / 'quickshell/caelestia'))).expanduser().resolve()
    content = shell_dir / 'modules/dashboard/Content.qml'
    if not (shell_dir / 'shell.qml').is_file() or not content.is_file():
        raise RuntimeError('Caelestia was not found at ' + str(shell_dir) + '. Use --shell-dir PATH for a custom installation.')
    original = content.read_text()
    updated = remove_navigation(original) if args.uninstall else patch_navigation(original)
    backup_dir = shell_dir / 'equalizer-installer-backups' / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup_dir.mkdir(parents=True)
    if args.uninstall:
        shutil.copy2(content, backup_dir / 'Content.qml')
        atomic_write(content, updated)
        for target in (content.parent / 'EqualizerTab.qml', content.parent / 'sound/easyeffects.py'):
            if target.exists():
                shutil.copy2(target, backup_dir / target.name)
                target.unlink()
        if updated != original and not args.no_restart:
            reload_shell(shell_dir)
        print('Equalizer tab removed. EasyEffects, its audio settings and autostart were kept.')
        return
    if args.no_packages:
        verify_easyeffects()
        if not shutil.which('qs'):
            raise RuntimeError('Quickshell (qs) is required.')
    else:
        require_dependencies(False)
    # Complete and verify audio setup before patching the dashboard.
    if not args.no_audio_setup:
        setup_audio(config_home, backup_dir)
    if not args.no_autostart:
        setup_autostart(config_home, backup_dir)
    install_preset(data_home)
    target_files = [(HERE / 'assets/EqualizerTab.qml', content.parent / 'EqualizerTab.qml'),
                    (HERE / 'assets/sound/easyeffects.py', content.parent / 'sound/easyeffects.py')]
    changed = updated != original or any(not target.exists() or target.read_bytes() != source.read_bytes() for source, target in target_files)
    if changed:
        shutil.copy2(content, backup_dir / 'Content.qml')
        originals = {content: original}
        try:
            for source, target in target_files:
                originals[target] = target.read_text() if target.exists() else None
                if target.exists():
                    shutil.copy2(target, backup_dir / target.name)
                atomic_write(target, source.read_text())
            atomic_write(content, updated)
        except Exception:
            for target, text in originals.items():
                if text is None:
                    target.unlink(missing_ok=True)
                else:
                    atomic_write(target, text)
            raise
        print('Installed Equalizer tab. Backups:', backup_dir)
    else:
        print('Equalizer tab is already up to date.')
    if not args.no_restart:
        reload_shell(shell_dir)
    print('Ready. Open the top dashboard and select Equalizer.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, configparser.Error, subprocess.SubprocessError) as error:
        print('Installation failed:', error, file=sys.stderr)
        sys.exit(1)
