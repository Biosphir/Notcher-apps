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

## Build and release

Run `python build_packages.py --tag apps-v1.0.0` to generate packages and a catalog in `dist/`. Every catalog entry contains its package URL, size and SHA-256 checksum.

To release changes, update the affected app's `manifest.json` and its entry in `catalog.json`, commit, then push a new `apps-v*` tag. GitHub Actions publishes each package and the catalog as release assets. App versions are independent of the release tag.

The live catalog is available at https://github.com/Biosphir/Notcher-apps/releases/latest/download/catalog.json.

## Host API

These packages target Notcher 1.8.3 plugin API 1 and run in its Python/Qt process. The host supplies PySide6, the PDF conversion runtime, `notcher_widgets`, and the `shared` modules. Plugins use the host's existing tool views and file-dialog lifecycle. Apps with ui set to "window" provide a standalone QWidget class; Notcher keeps one window per app and closes it on uninstall or exit.

PDF Converter has a pinned bundled copy in the Notcher repository. A Notcher build includes that copy and the shared runtime. Optional app source is loaded from the installed package directory.

Packages contain their manifest and app folder. Additional third-party dependencies require host runtime support in this first version.

## Share Screen

Both users install Share Screen in Notcher. The sharing user selects **Start sharing**, chooses a display or window, and sends the invitation code to the viewer. The viewer selects **Join a screen**, pastes the invitation, and returns the generated response code. The sharing user pastes that response and selects **Connect**.

Video uses a direct WebRTC connection with a public STUN server for network discovery. This first release uses manual code exchange and has no TURN relay. Some firewall or NAT configurations require a different network. Either user can stop the session. Closing the app stops its capture and connection.

## Extended Display

This Windows app lists active displays and applies the Windows Extend topology to monitors connected to the PC. Windows display settings is available for monitor arrangement and other settings. The app reports native configuration errors if the connected hardware or Windows session cannot apply Extend mode.
