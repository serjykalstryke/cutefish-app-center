# Changelog

## 0.3.1 — 2026-11-06

- Present one search entry per application across Debian, Flatpak, Snap and AppImage, with available formats listed on the card.
- Extend identity matching with desktop/common catalog IDs and unambiguous exact name/package aliases, while keeping unrelated namesakes and distinct editions separate.
- Add installation status to source choices, favor existing installations, and remember the selected source during the session.
- Keep the application title stable while source-specific metadata, versions and actions change; preserve every exact installation target.
- Apply search limits to application groups so included apps retain all their source choices.
- Add cross-provider grouping and native source-switching regressions.

## 0.3.0 — 2026-11-05

- Combine Installed and Updates into one panel, with update rows first, application-only defaults, All software and Updates only filters.
- Identify desktop apps from catalog metadata and visible launchers, keeping libraries, services and runtimes accessible without cluttering the default list.
- Add Update All for every configured source, including Debian system packages, Flatpak runtimes and Snap bases, with a full review independent of list filters.
- Use libflatpak for structured update inventory and reviewed update transactions, including exact commits and related runtime changes.
- Recheck plans before modification, preserve held/protected packages, stop later sources after a failure, and report completed changes and restart requirements.
- Check updates separately in the background and keep installed software usable when an update source is unavailable.

## 0.2.3 — 2026-11-05

- Rebuild with Debian's installed compiler and shared C++ runtime to fix the launch failure after the Cutefish toolkit update.
- Refuse packaging when the binary lacks a direct shared C++ runtime dependency, has missing libraries, or has unresolved runtime symbols.
- Document clean rebuilds after toolkit changes and add packaging regression checks.

## 0.2.2 — 2026-11-04

- Show Snap Store and AppImageHub icons before installation with a separate asynchronous loader for visible result rows.
- Cache validated artwork, reuse offline copies, and read installed Snap icons through snapd's local endpoint. Imported AppImage artwork remains unchanged.
- Cancel outdated icon requests on navigation and limit concurrent work; missing artwork does not block search or software operations.

## 0.2.1 — 2026-11-04

- Read Debian's AppStream/DEP-11 YAML catalogs using libappstream and show cached repository icons before installation, including search, details, Discover and Updates.
- Include the standard AppStream and APT icon-cache dependencies; document the initial metadata refresh.
- Keep APT package identity and generic artwork fallback when catalogs or app icons are unavailable.

## 0.2.0 — 2026-11-04

- Rename the app, repository, binary, package, desktop ID, artwork and data paths to Cutefish App Center.
- Add an upgrade path from cutefish-store and migrate validated AppImage imports, artwork paths and generated launchers without touching original downloads.
- Rework Discover into a manual featured-app carousel and category grid, populated from configured catalogs.
- Retain the search-and-details split view when selecting featured apps or categories.
- Add dedicated Install from File and About sidebar pages; About credits David Stinnett.
- Remove feature-list copy, local-file instructions and catalog refresh controls from Discover; refresh controls remain under Updates and the Software menu.
- Add coverage for featured availability, all categories, migration, carousel navigation and file-drop review.

## 0.1.4 — 2026-11-04

- Add on-demand app details with publisher, full descriptions, versions, license and project website where sources provide them.
- Show catalog icons and a cached screenshot gallery with navigation and an enlarged viewer. Preserve usable app details when artwork is offline.
- Add Open for installed desktop apps, bound to their selected package, Flatpak scope/ref, Snap launcher or managed AppImage launcher.
- Export the application-name, File, View, Software and Help menus to Cutefish's universal menu, with working keyboard shortcuts.
- Extend the sidebar to the top of the window and remove its internal corner radius.
- Add metadata/artwork/launcher regressions and a native details test covering source changes, Open dispatch, gallery, menu registration and sidebar placement.

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
