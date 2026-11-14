# Changelog

## 1.0.2

- Send only edited bands during slider adjustments instead of writing a full preset.
- Avoid reading every band before an edit; retain stereo write verification and a complete readback afterward.
- Merge queued edits by band and prevent older replies from overwriting newer edits.
- Preserve the ordering of rapid edits and preset changes.

This reduces control-socket traffic during adjustments. It is not a confirmed fix for reports of dashboard or visualizer lag while idle.

## 1.0.1

- Add a desktop video preview with music and equalizer preset changes.
- Use the supplied recording for the MP4 and silent GIF previews.
- Include close-up screenshots and document the preview media.

## 1.0.0

- Add the Caelestia dashboard equalizer with animated band controls and a gain curve.
- Include eleven presets, mouse-wheel adjustment, keyboard control, and per-band reset.
- Keep editing responsive while queuing and verifying EasyEffects updates.
- Install native EasyEffects and LSP LV2 dependencies on Arch Linux / CachyOS.
- Start EasyEffects, add a flat equalizer when missing, and register session startup.
- Preserve existing equalizer tuning, other output effects, microphone settings, and blocklists.
- Include backups, uninstall support, regression tests, screenshots, and a silent MP4/GIF demo.
- Correct boolean encoding for the EasyEffects bypass control.
