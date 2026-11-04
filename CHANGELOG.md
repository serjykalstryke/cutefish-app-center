# Changelog

## 0.1.3 — 2026-11-04

- Rank search results by relevance before limiting them, with exact app/package names first.
- Recognize browser, editor and player category queries and aliases using provider metadata.
- Search cached Flatpak AppStream categories/keywords, including legacy desktop components, while retaining exact remote, scope, branch and architecture.
- Search Debian summaries as well as names, with optional AppStream XML enrichment.
- Filter incidental description matches and helper packages from category searches; prefer stable desktop apps over launchers and experimental builds.
- Make Discover shortcuts perform real category searches and show that results are ranked.
- Add search regression coverage and extend the native UI smoke test to verify browser discovery.

## 0.1.2 — 2026-11-04

- Read type-2 AppImage desktop metadata and PNG/SVG artwork without executing the image.
- Refresh metadata for existing imports, including names, categories and window matching.
- Document source builds, uninstalled runs, tests and local Debian packaging.
- Recommend Debian 13's `libfuse2t64` AppImage compatibility library during store installation. FUSE 3 alone does not provide `libfuse.so.2` required by older AppImage runtimes.
- Desktop testing confirmed Flatpak Firefox installation, AppImage catalog/download handoff, and application removal.

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
