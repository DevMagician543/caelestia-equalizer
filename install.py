#!/usr/bin/env python3
"""Install the equalizer in Caelestia's Media tab and set up native EasyEffects."""

import argparse
import configparser
from contextlib import ExitStack
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
DASHBOARD_ASSETS = ('sound/easyeffects.py', 'equalizer/EqualizerState.qml', 'equalizer/qmldir',
                    'EqualizerTab.qml', 'MediaEqualizer.qml')


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


MEDIA_PAGE = re.compile(r'(^[ \t]*id:[ \t]*mediaComponent[ \t]*\n\s*)Media(?:Equalizer)?(?=\s*\{)', re.M)
MEDIA_BACKGROUND = '''    BackgroundShapes {
        anchors.fill: parent
    }
'''
MEDIA_BACKGROUND_PATCH = '''    // >>> caelestia-equalizer: Media background >>>
    property bool showMediaBackground: true

    Loader {
        anchors.fill: parent
        active: root.showMediaBackground
        sourceComponent: BackgroundShapes {}
    }
    // <<< caelestia-equalizer: Media background <<<
'''


def patch_media_background(original):
    if MEDIA_BACKGROUND_PATCH in original:
        return original
    if original.count(MEDIA_BACKGROUND) != 1 or 'showMediaBackground' in original:
        raise RuntimeError('Unsupported Caelestia dashboard: could not identify the Media background. '
                           'No dashboard files were changed.')
    return original.replace(MEDIA_BACKGROUND, MEDIA_BACKGROUND_PATCH, 1)


def remove_media_background_patch(original):
    return original.replace(MEDIA_BACKGROUND_PATCH, MEDIA_BACKGROUND, 1)


def patch_navigation(original):
    updated, media_pages = MEDIA_PAGE.subn(r'\g<1>MediaEqualizer', original)
    if media_pages != 1:
        raise RuntimeError('Unsupported Caelestia dashboard: could not find the Media page. '
                           'No dashboard files were changed.')
    if 'component: soundComponent' in original:
        raise RuntimeError('An earlier Sound tab is present. Migrate it before installing.')
    return remove_standalone_tab(updated)


def remove_navigation(original):
    return remove_standalone_tab(MEDIA_PAGE.sub(r'\g<1>Media', original, count=1))


def remove_standalone_tab(original):
    uses = len(re.findall(r'\bcomponent:\s*equalizerComponent\b', original))
    definitions = len(re.findall(r'\bid:\s*equalizerComponent\b', original))
    entry = re.compile(r'^[ \t]*\{\s*component:\s*equalizerComponent,\s*iconName:\s*"equalizer",'
                       r'\s*text:\s*qsTr\("Equalizer"\),\s*enabled:\s*true\s*\},\n?', re.M)
    updated, entries = entry.subn('', original)
    component = re.compile(r'^[ \t]*Component\s*\{\s*id:\s*equalizerComponent\s*'
                           r'EqualizerTab\s*\{\s*\}\s*\}\n{0,2}', re.M)
    updated, components = component.subn('', updated)
    if entries != uses or components != definitions or uses > 1 or definitions > 1:
        raise RuntimeError('Equalizer navigation was customized; refusing to remove unrelated code.')
    return updated


WRAPPER_ACTIVE = 'root.shouldBeActive || root.visible'
WRAPPER_CACHED = WRAPPER_ACTIVE + ' || root.equalizerPageRetained'
WRAPPER_LOAD_HANDLER = '        onLoaded: Qt.callLater(root.updateEqualizerPageRetention)\n'
WRAPPER_CACHE_BLOCK = """    // >>> caelestia-equalizer: selected page cache >>>
    property bool equalizerPageRetained: false

    function updateEqualizerPageRetention() {
        const tabs = (content.item as Content)?.dashboardTabs;
        equalizerPageRetained = !!tabs && tabs[root.screenState.dashboardTab]?.iconName === "equalizer";
    }

    Connections {
        target: root.screenState
        function onDashboardTabChanged() { Qt.callLater(root.updateEqualizerPageRetention); }
        function onDashboardChanged() { Qt.callLater(root.updateEqualizerPageRetention); }
    }
    // <<< caelestia-equalizer: selected page cache <<<
"""


def remove_wrapper_patch(original):
    if WRAPPER_CACHE_BLOCK not in original:
        return original
    return (original.replace(WRAPPER_CACHE_BLOCK + '\n', '')
            .replace(WRAPPER_LOAD_HANDLER, '')
            .replace(WRAPPER_CACHED, WRAPPER_ACTIVE))


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


def has_dashboard(path):
    return (path / 'shell.qml').is_file() and (path / 'modules/dashboard/Content.qml').is_file()


def system_shell_dirs():
    roots = os.environ.get('XDG_CONFIG_DIRS') or '/etc/xdg'
    return [Path(root) / 'quickshell/caelestia' for root in roots.split(':') if Path(root).is_absolute()]


def find_shell(config_home, override, uninstall):
    """Return the source directory and the directory the installer may edit."""
    user_shell = config_home / 'quickshell/caelestia'
    system_dirs = system_shell_dirs()
    if override is not None:
        source = Path(override).expanduser().resolve()
        if not has_dashboard(source):
            raise RuntimeError(f'Caelestia was not found at {source}. Pass the directory containing shell.qml to --shell-dir.')
    elif has_dashboard(user_shell):
        source = user_shell.resolve()
    else:
        running = set()
        if shutil.which('qs'):
            result = command('qs', 'list', '--all', check=False)
            for match in re.finditer(r'^\s*Config path: (.+)$', result.stdout, re.M):
                config = Path(match.group(1).strip().strip('"'))
                candidate = config.parent.resolve()
                # Other Quickshell configs can be running in the same session.
                if (config.name == 'shell.qml' and has_dashboard(candidate) and
                        'import Caelestia' in (candidate / 'modules/dashboard/Content.qml').read_text()):
                    running.add(candidate)
        if len(running) > 1:
            choices = ', '.join(str(path) for path in sorted(running))
            raise RuntimeError(f'Multiple Caelestia shells are running: {choices}. Choose one with --shell-dir.')
        source = next(iter(running), None)
        if source is None:
            source = next((path.resolve() for path in system_dirs if has_dashboard(path)), None)
        if source is None:
            raise RuntimeError(f'Caelestia was not found. Checked {user_shell} and the system config directories. '
                               'Start Caelestia and retry, or use --shell-dir with the folder containing shell.qml.')

    protected = source in {path.resolve() for path in system_dirs} or any(
        source.is_relative_to(root) for root in (Path('/etc'), Path('/usr'), Path('/nix/store'))
    )
    if protected or not os.access(source / 'modules/dashboard', os.W_OK):
        if uninstall:
            raise RuntimeError(f'No writable Equalizer installation at {source}. Use --shell-dir for a custom user copy.')
        if user_shell.exists() or user_shell.is_symlink():
            raise RuntimeError(f'Cannot create a user copy at {user_shell} because that path already exists. '
                               'Choose a writable Caelestia config with --shell-dir.')
        return source, user_shell
    return source, source


def shell_running(shell_dir):
    return 'Instance ' in command('qs', '-p', str(shell_dir), 'list', check=False).stdout


def switch_shell(source, destination):
    command('qs', '-p', str(source), 'kill')
    for _ in range(50):
        if not shell_running(source):
            break
        time.sleep(0.1)
    else:
        raise RuntimeError('The old Caelestia instance did not stop. Restart it to use the user copy.')
    try:
        command('qs', '-p', str(destination), '-n', '-d')
    except subprocess.SubprocessError:
        command('qs', '-p', str(source), '-n', '-d', check=False)
        raise RuntimeError(f'Could not start Caelestia from {destination}. The installer requested a restart of the original shell.') from None
    print('Caelestia restarted with the user config.')


def reload_shell(shell_dir):
    if not shell_running(shell_dir):
        print('Caelestia is not running; the tab will appear on its next start.')
        return
    result = command('qs', '-p', str(shell_dir), 'ipc', 'call', 'appearance', 'reloadShell', check=False)
    if result.returncode == 0:
        print('Caelestia configuration reloaded.')
        return
    command('qs', '-p', str(shell_dir), 'kill')
    for _ in range(50):
        if not shell_running(shell_dir):
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
    parser.add_argument('--uninstall', action='store_true', help='Remove the Media equalizer; keep audio settings and packages')
    parser.add_argument('--shell-dir', type=Path, help='Path to the existing Caelestia Quickshell configuration')
    args = parser.parse_args(argv)
    if os.geteuid() == 0:
        raise RuntimeError('Run ./install.sh as your normal desktop user, not with sudo. '
                           'Only package installation uses sudo.')
    config_home = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')).expanduser().resolve()
    data_home = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share'))
    override = args.shell_dir if args.shell_dir is not None else os.environ.get('CAELESTIA_DIR') or None
    source, shell_dir = find_shell(config_home, override, args.uninstall)
    dashboard = source / 'modules/dashboard'
    patches = {}
    for filename, install, uninstall in (
        ('Media.qml', patch_media_background, remove_media_background_patch),
        ('Wrapper.qml', remove_wrapper_patch, remove_wrapper_patch),
        ('Content.qml', patch_navigation, remove_navigation),
    ):
        path = dashboard / filename
        if not path.is_file():
            if filename == 'Wrapper.qml' or (args.uninstall and filename == 'Media.qml'):
                continue
            raise RuntimeError('Caelestia dashboard file was not found at ' + str(path))
        original = path.read_text()
        updated = (uninstall if args.uninstall else install)(original)
        if updated != original:
            patches[filename] = (original, updated)
    with ExitStack() as cleanup:
        install_dir = shell_dir
        if source != shell_dir:
            shell_dir.parent.mkdir(parents=True, exist_ok=True)
            staging = Path(cleanup.enter_context(tempfile.TemporaryDirectory(prefix='.equalizer-', dir=shell_dir.parent)))
            install_dir = staging / 'caelestia'
            shutil.copytree(source, install_dir)
            # Package modes can be read-only, even on a user-owned copy.
            for directory, _, _ in os.walk(install_dir):
                path = Path(directory)
                path.chmod(path.stat().st_mode | 0o700)
        backup = install_equalizer(args, config_home, data_home, install_dir, patches)
        if source != shell_dir:
            if shell_dir.exists() or shell_dir.is_symlink():
                raise RuntimeError(f'{shell_dir} appeared during installation. Existing config kept.')
            install_dir.rename(shell_dir)
            print(f'Installed a user copy of Caelestia at {shell_dir}.')
    if not args.uninstall:
        if backup is not None:
            print('Installed Equalizer. Backups:', shell_dir / backup)
        original_content, _ = patches.get('Content.qml', ('', ''))
        if re.search(r'\bcomponent:\s*equalizerComponent\b', original_content):
            print('Moved the existing Equalizer tab into Media. EasyEffects settings were kept.')
        if not args.no_restart:
            if source != shell_dir and shell_running(source):
                switch_shell(source, shell_dir)
            elif not shell_running(shell_dir) and shell_dir == config_home / 'quickshell/caelestia':
                packaged = next((path.resolve() for path in system_shell_dirs()
                                 if has_dashboard(path) and shell_running(path.resolve())), None)
                if packaged is not None:
                    switch_shell(packaged, shell_dir)
                else:
                    reload_shell(shell_dir)
            else:
                reload_shell(shell_dir)
        print('Ready. Open the Media tab and expand Equalizer.')


def install_equalizer(args, config_home, data_home, shell_dir, patches):
    dashboard = shell_dir / 'modules/dashboard'
    target_files = [(HERE / 'assets' / path, dashboard / path) for path in DASHBOARD_ASSETS]
    backup_dir = shell_dir / 'equalizer-installer-backups' / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup_dir.mkdir(parents=True)
    if args.uninstall:
        for filename, (_, updated) in reversed(patches.items()):
            shutil.copy2(dashboard / filename, backup_dir / filename)
            atomic_write(dashboard / filename, updated)
        for _, target in target_files:
            if target.exists():
                shutil.copy2(target, backup_dir / target.name)
                target.unlink()
        if patches and not args.no_restart:
            reload_shell(shell_dir)
        print('Equalizer removed from the dashboard. EasyEffects, its audio settings and autostart were kept.')
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
    changed_files = [(source, target) for source, target in target_files
                     if not target.exists() or target.read_bytes() != source.read_bytes()]
    if patches or changed_files:
        originals = {}
        try:
            for source, target in changed_files:
                originals[target] = target.read_text() if target.exists() else None
                if target.exists():
                    shutil.copy2(target, backup_dir / target.name)
                atomic_write(target, source.read_text())
            for filename, (original, updated) in patches.items():
                target = dashboard / filename
                shutil.copy2(target, backup_dir / filename)
                originals[target] = original
                atomic_write(target, updated)
        except Exception:
            for target, text in originals.items():
                if text is None:
                    target.unlink(missing_ok=True)
                else:
                    atomic_write(target, text)
            raise
        return backup_dir.relative_to(shell_dir)
    print('Equalizer is already up to date.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, configparser.Error, subprocess.SubprocessError) as error:
        print('Installation failed:', error, file=sys.stderr)
        sys.exit(1)
