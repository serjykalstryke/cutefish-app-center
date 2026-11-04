# Validation — November 4, 2026

Built on Debian 13 amd64 against the installed native Cutefish toolkit:
`1.0~git20261102154148.6106b19-1+nordos.snap1`.

## Initial prototype checks

- CMake Release configuration and build with GCC 14.2.0, including the optional native smoke-test target. C++ compilation with `-Wall -Wextra -Wpedantic` produced no diagnostics.
- 15 backend tests: local Debian inspection, AppImage import/remove without execution, retained downloads, duplicate/changed files, invalid IDs, Flatpak scope/ref/branch retention, exact Debian update architecture, provider failure isolation, stale plans, protected Debian removals, classic Snap review, update limits, and transaction locking.
- 2 protocol tests against a private PackageKit D-Bus service using Debian 13's PackageKit 1.3.1 client library. Covered Resolve, InstallPackages/RemovePackages simulation, legacy SetHints, signals, and error propagation. These are protocol tests, not tests of the real APT backend.
- Native headless UI smoke test using actual backend inventory: clicked Installed, received async inventory, typed an installed-software filter, and returned to Discover.
- AppImage desktop Exec escaping checked with the installed Cutefish desktop-entry parser, including spaces, backslashes, quotes, dollar signs, backticks and percent signs.
- Headless screenshot rendered and visually inspected at 1120 × 800. The shared preview image intentionally contains sample entries with operations disabled.
- Live read-only inventory: 880 installed Debian packages and 9 Snap entries. Live Snap catalog query returned results.
- Flatpak CLI availability, remotes and installed inventory checked. Flathub is configured system-wide; no Flatpak apps were installed. Search returned no matches with the current local catalog state.
- Generated Debian package inspected; no maintainer scripts or privileged helper are included. APT installation simulation resolved it with PackageKit and its client library, with no removals.

## Initial prototype limitations

No real application installation, removal, upgrade, repository change or catalog refresh was performed. PackageKit is absent from the host, so its actual APT backend and Polkit flow remain untested. Flatpak/Snap mutations, file chooser interaction, actual AppImage launching, authentication failure and recovery, accessibility and localization need further validation.

PackageKit and build-tool packages used by tests were downloaded and extracted into the working directory, not installed. Test AppImages and Debian fixtures were created in temporary directories. The provided `.deb` declares the missing runtime dependencies.

## 0.1.1 follow-up

- The desktop user confirmed real native Debian and Snap installs with 0.1.0.
- Reproduced the reported Flatpak failure: `remote-info --show-permissions` is
  unsupported by installed Flatpak 1.16.6.
- Corrected it to `remote-info --show-metadata`; a live GIMP install review now
  returns application Context and bus access declarations without modifying
  the installation. An apply regression test checks the exact scoped command.
- Live Flatpak search now filters against actual app refs, excluding GIMP's
  runtime extensions and plugins.
- Live AppImageHub catalog query finds Krita and creates its catalog-page link.
  Tests cover catalog caching, markup cleanup, and URI reconstruction.
- 20 backend regression tests and 2 private PackageKit protocol tests passed.
- Rebuilt the native app and passed the headless inventory/filter/navigation test.
- Original vector store icon compared visually with installed Cutefish icons;
  its rounded light tile, blue shopping bag and app grid match the desktop's
  visual style. Artwork was created for this project, not copied from the theme.
- A real Flatpak install and browser download/import flow still need desktop
  confirmation. No live software changes were made by the development checks.

## 0.1.2 follow-up

- The user confirmed AppImage import and software-menu launch after installing `libfuse2t64`.
- Reproduced the imported-icon issue: the generated launcher used a generic icon.
- Read the Firefox Nightly AppImage's embedded `firefox-nightly.desktop` and 12,392-byte PNG through `unsquashfs`, without executing the image.
- Preserve Name=Firefox Nightly, Comment=Browse the Web, categories and StartupWMClass=Nightly. The source Exec=/opt/firefox-nightly/firefox is deliberately not copied; the launcher retains the managed AppImage path.
- Added real SquashFS fixtures covering artwork import, internal/external symlinks, existing-import repair, oversized artwork, external SVG resources and missing tooling.
- 27 backend tests and 2 private PackageKit protocol tests passed. The protocol tests were run in the Cutefish terminal. A fresh out-of-tree Release build with GCC 14.2.0 and the native headless integration test also passed.
- README now starts with complete source-build instructions and local `.deb` creation; generated packages remain excluded from Git.

## 0.1.3 search follow-up

- 27 existing backend tests, 15 search regression tests and 2 private PackageKit protocol tests passed.
- Search fixtures cover singular/plural category aliases, unfamiliar app names, exact app/package queries, helper filtering, ranking before limits, deterministic ordering, provider errors, AppImage discovery, and unchanged Installed/Updates ordering.
- Flatpak metadata fixtures cover legacy `desktop` components, English fields, categories/keywords and exact available branch/architecture/remote/scope matching. Category candidates absent from available refs are excluded.
- Live `web browsers` search on this system returned browser-focused results including Brave, Firefox, Chromium and Google Chrome. The former results included unrelated apps such as CouchDB and Ascii Patrol. Live searches for Firefox, image editors, text editors and media players also completed without provider errors; measured search completion was about 1.6–1.8 seconds with warm catalogs.
- Built both native targets without compiler diagnostics. The extended headless integration test passed: real inventory/filter navigation, the Web browsers shortcut, ranked results, and Brave/Google Chrome/Firefox presence; chromium-sandbox was absent from browser discovery.
- Search uses existing configured catalogs and read-only provider queries. No application install/removal, repository additions or metadata refresh was needed for these search checks. Catalog categorization remains dependent on publisher metadata; Debian YAML AppStream support is not included.

## 0.1.4 app details and desktop integration

- 27 backend, 15 search, 19 details/artwork/launch and 2 private PackageKit protocol tests passed (63 total).
- Details tests cover English publisher metadata, full descriptions, icon/screenshot selection, offline artwork reuse, invalid artwork bounds, exact Flatpak origin/ref checks, package-owned launchers, managed AppImage launchers, Snap offline fallback and non-launchable catalog entries/services. A real Gio DesktopAppInfo launch runs only a private fixture that writes a temporary marker.
- Built the app and both optional native test targets without compiler diagnostics. Assertions remain enabled for both smoke targets in Release builds.
- Native inventory/search smoke passed with actual providers. The private native details test passed source switching, Open request dispatch, gallery navigation/enlargement, main-menu role registration and top-aligned sidebar geometry; its provider never launches software or changes packages.
- The live native details test rendered actual Firefox metadata, Mozilla publisher information, cached icon and all three catalog screenshots. Live read-only checks also resolved Chromium's installed desktop launcher and fetched VLC's Snap publisher/media metadata.
- An actual Cutefish session displayed the application-name menu and File, View, Software and Help entries in the universal top bar. The sidebar reaches the top of the window; its internal corner radius is zero in the final build.
- Missing publisher fields and screenshots remain source-dependent. Imported AppImages do not gain screenshots unless a source provides them. No real application installation/removal or repository change was needed for these checks.


## 0.2.0 App Center and browsing UI

- Renamed repository, CMake project, executable, backend, environment overrides,
  package, desktop/icon/AppStream identity, paths and documentation. Historical
  copyright notices and explicit upgrade compatibility keep the old name.
- 74 checks passed: 27 backend, 15 search, 19 details/artwork/launch,
  11 Discover/migration and 2 private PackageKit protocol tests.
- Discover fixtures require advertised exact app refs, omit unavailable picks,
  isolate provider errors, support Debian-only fallback and cover all eight
  category mappings. Migration fixtures cover preserved image bytes/artwork,
  original downloads, interrupted moves, duplicate imports, changed archives,
  legacy symlinks and active legacy transactions.
- Release build and all three native smoke tests passed. Native navigation
  covers carousel paging, category search, About author/version, file-drop
  review, return navigation and the retained search/details experience.
- Live read-only Discover resolved six available applications from configured
  catalogs in about 1.1 seconds. Discover, About and Install from File were
  rendered and visually checked with the native toolkit. Fixture tests never
  launch real applications or mutate installed software.
- APT simulation replaces only `cutefish-store` 0.1.4 with
  `cutefish-app-center` 0.2.0 and needs no additional dependencies on this host.
  This simulation and the private transaction tests do not establish a real
  package upgrade or real-library migration; those require desktop validation.


## 0.2.1 Debian artwork before installation

- Added libappstream's OS-only catalog reader for XML/DEP-11 YAML, including
  repository icon caches, names, categories and existing details metadata.
  Flatpak components and installed desktop files are excluded from this pool.
- 81 backend/protocol checks passed, including seven tests that load actual
  DEP-11 fixtures through Debian 13's libappstream 1.0.5. They cover uninstalled
  app icons without network requests, missing artwork, source/package identity,
  unavailable package exclusion, details and PackageKit update identity.
- Release build and the inventory/search, details and home native smoke tests
  passed. The installed UI was inspected showing Debian category results with
  repository artwork for applications that were not installed.
- Installed App Center 0.2.1 with appstream, apt-config-icons and the AppStream
  introspection bindings, then refreshed APT metadata. No applications were
  installed to obtain their icons. The catalog reader found 1,871 desktop
  package records in about 1.1 seconds on this machine.
- Live Debian searches resolved existing cached PNG files for uninstalled GIMP,
  Krita, Inkscape, Firefox ESR and Blender. Search does not fetch full packages
  or remotely download each result's icon; normal APT refreshes maintain the
  catalog and cache. Repositories without app metadata retain generic icons.
