# Notcher Apps

Each app is released as an independent `.notcher-app` ZIP package. Notcher downloads only the selected package.

| Folder | App | Included in a fresh Notcher installation |
| --- | --- | --- |
| pdf_converter | PDF Converter | Yes |
| pdf_merger | PDF Merger | No |
| pdf_split | PDF Split | No |
| quick_search | Quick Search | No |
| share_screen | Share Screen | No |
| extended_display | Extended Display | No |
| screen_recorder | Screen Recorder | No |
| focus_timer | Focus Timer | No |
| color_picker | Color Picker | No |
| live_lyrics | Live Lyrics | No |

## Build and release

Run `python build_packages.py --tag apps-v1.0.0` to generate packages and a catalog in `dist/`. Every catalog entry contains its package URL, size and SHA-256 checksum.

To release changes, update the affected app's `manifest.json` and its entry in `catalog.json`, commit, then push a new `apps-v*` tag. GitHub Actions publishes each package and the catalog as release assets. App versions are independent of the release tag.

The live catalog is available at https://github.com/Biosphir/Notcher-apps/releases/latest/download/catalog.json.

## Host API

These packages target Notcher 1.8.3 plugin API 1 and run in its Python/Qt process. The host supplies PySide6, the PDF conversion runtime, `notcher_widgets`, and the `shared` modules. Plugins use the host's existing tool views and file-dialog lifecycle. Apps with ui set to "window" provide a standalone QWidget class; Notcher keeps one window per app and closes it on uninstall or exit. Use the shared NotcherWindow and NotcherDialog classes from shared.window for consistent frameless chrome, rounded black surfaces, controls and fonts. The host also supplies NotcherFileDialog and NotcherMessageBox for file selection and messages.

PDF Converter has a pinned bundled copy in the Notcher repository. A Notcher build includes that copy and the shared runtime. Optional app source is loaded from the installed package directory.

Packages contain their manifest and app folder. Additional third-party dependencies require host runtime support in this first version.

## Share Screen

Both users install Share Screen in Notcher. The sharing user selects **Start sharing**, chooses a display or window, and sends the invitation code to the viewer. The viewer selects **Join a screen**, pastes the invitation, and returns the generated response code. The sharing user pastes that response and selects **Connect**.

Video uses a direct WebRTC connection with a public STUN server for network discovery. This first release uses manual code exchange and has no TURN relay. Some firewall or NAT configurations require a different network. Either user can stop the session. Closing the app stops its capture and connection.

## Extended Display

This Windows app lists active displays and applies the Windows Extend topology to monitors connected to the PC. Windows display settings is available for monitor arrangement and other settings. The app reports native configuration errors if the connected hardware or Windows session cannot apply Extend mode.

## Screen Recorder

Choose a display and an output path to record an MP4 video. Recording supports pause, resume, a preview and elapsed time. Closing the window stops and saves the recording. An available MP4/H.264 encoder is required.

## Focus Timer

Focus and short/long break durations are adjustable. After four focus sessions, the next break is a long break. Each completed phase emits a notification through Notcher and waits for the user to start the next phase. Minimize keeps the timer running; closing it stops the session.

## Color Picker

The picker freezes snapshots of connected displays. Click a pixel to select its color, or press Escape to cancel. The app displays and copies HEX and RGB values and remembers the last selected color.

## Live Lyrics

Installing Live Lyrics enables the microphone icon on the left of Music Overview's playback controls. The host binds the active media controller to the app's bind_music method. The popup follows song changes, pause, resume and seek through the controller's media_snapshot API.

Lyrics and timestamps are retrieved from LRCLIB using title, artist, album and duration. The client identifies itself with a User-Agent, performs requests off the UI thread, respects rate-limit responses, and stores a bounded SQLite cache on the device. Playback position stays local.

Matching uses title, artist and duration. Matching records are selected automatically, preferring the highest LRCLIB record ID among equally close matches. LRCLIB does not expose a revision timestamp. Timed LRC lines are highlighted and followed automatically; plain lyrics are displayed as unsynced. Manual scrolling pauses following until Follow song is selected. Refresh bypasses the cached result. Instrumental, missing metadata, unavailable lyrics and service/network failures have dedicated states.

The popup defaults to 480 × 280, with large bold lyrics on a muted plum gradient inside the rounded Notcher frame. Song title and artist labels are hidden. About three to four short lines fit; wrapped lines take more room. The host hides/restores the opened panel with Music Overview and notch visibility, and keeps it anchored below the host. The microphone toggles the panel open/closed; window-control buttons are hidden. Initial lyrics retrieval requires internet access. Cache hits can be displayed offline.
