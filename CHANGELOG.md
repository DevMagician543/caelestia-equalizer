# Changelog

## 1.1.0

- Move the equalizer into an expandable section below the playback controls in Media.
- Migrate existing installations automatically. The installer removes the old standalone tab and its page-retention patch, backs up changed dashboard files, and preserves EasyEffects settings.
- Share equalizer state across the controls and the collapsed header so the selected preset remains visible.
- Recover the original EasyEffects configuration if a fresh audio setup cannot be verified.
- Roll back partial dashboard changes on installer and uninstaller write failures.
- Report a shell restart timeout when the old process remains running.
- Use the original MP4 and show the full frame in the README preview.

## 1.0.4

- Detect custom Caelestia paths from running Quickshell instances and find packaged configs in the system XDG directories.
- Install into a user-owned copy for packaged configs and restart a running packaged shell with that copy.
- Simplify the Equalizer header while keeping the switch and footer controls.

## 1.0.3

- Retain the dashboard content while Equalizer is selected, avoiding repeated control construction during the drawer’s opening animation.
- Build the Equalizer controls asynchronously on first use.
- Pause polling while hidden and refresh settings when the retained page becomes visible again.
- Populate the band model in one batch.
- Back up and restore the targeted dashboard-wrapper change during install and uninstall.

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
