# Equalizer opening check — 1.0.3

The dashboard wrapper previously unloaded its content after the drawer closed. Opening Equalizer again constructed its controls, then created band delegates when the helper returned settings, during the opening transition.

The installer now adds a small, reversible wrapper integration: it retains the dashboard content while the selected tab is Equalizer. Selection is checked using the actual tab list, so disabled tabs and additional dashboard tabs are respected. A deferred event handler updates the retention flag; `Loader.active` does not depend on its own `item`.

Equalizer's visual tree is also built by an asynchronous Loader, and the initial band list is appended in a single batch. The retained page refreshes when visible and pauses its periodic polling while hidden. Selecting another tab restores the wrapper's usual unload behavior.

## Local checks

Measured using a temporary Qt Quick FrameAnimation probe in the running Caelestia shell, with a ten-band equalizer and 75/144 Hz displays. The first opening after a shell reload was measured separately from repeated openings. The probe and temporary IPC endpoints were removed afterward.

| Opening | Worst sampled GUI-thread frame interval before | After |
|---|---:|---:|
| Reopening 1 | 81 ms | 14 ms |
| Reopening 2 | 82 ms | 15 ms |
| Reopening 3 | 84 ms | 14 ms |
| First opening after reload | 145 ms | 130 ms |

These are local GUI-thread interval measurements, not guaranteed FPS figures or measurements on the reporter's hardware. Initial construction of the shell's whole dashboard still costs time; retaining Equalizer avoids paying that cost on every reopening.

A separate runtime check verified that the same page instance survives closing/reopening, no refresh occurs over 12.3 seconds while hidden, reopening refreshes settings, and selecting another tab releases the retained page. The installer tests cover fresh installation, upgrades of an existing tab, idempotency, and restoring the wrapper on uninstall.
