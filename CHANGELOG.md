# Changelog

## 0.1.1 — 2026-11-04

- Fix Flatpak install review: use supported remote metadata and show Context
  and bus-access declarations. Reject runtime metadata as an app.
- Filter Flatpak discovery through actual app refs, excluding plugins/runtimes.
- Add AppImageHub catalog search with a 24-hour metadata cache and explicit
  download-page handoff. Local import remains a separate review step.
- Add a Cutefish-style store icon, wired into the launcher/dock and sidebar.
- Add native window/sidebar branding configuration for NordOS packaging.
- Add contribution notes and Debian 13 backend CI.

## 0.1.0 — 2026-11-04

- Initial native Cutefish store prototype with Debian/Flatpak/Snap providers,
  dependency reviews and local Debian/AppImage file handling.
- Desktop user confirmed native Debian and Snap application installation.
