# Contributing

For a bug report, include your distribution, EasyEffects version, Caelestia revision or version, the message in the tab, and steps to reproduce. Remove personal device identifiers and paths from logs before sharing them.

Run `python3 -m unittest discover -s tests -v` and `bash -n install.sh` before submitting changes. Use `qmllint assets/EqualizerTab.qml` and test the tab in a compatible Caelestia installation when changing QML.

Installer changes must preserve existing effect chains, microphone settings, and equalizer gains. Add regression coverage for changes to configuration handling. Package-manager tests and CI should use temporary files or mocks, never a contributor's live audio setup.
