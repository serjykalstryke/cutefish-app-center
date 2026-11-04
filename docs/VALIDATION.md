# Validation — November 4, 2026

Built on Debian 13 amd64 against the installed native Cutefish toolkit:
`1.0~git20261102154148.6106b19-1+nordos.snap1`.

## Passed

- CMake Release configuration and build with GCC 14.2.0, including the optional native smoke-test target. C++ compilation with `-Wall -Wextra -Wpedantic` produced no diagnostics.
- 15 backend tests: local Debian inspection, AppImage import/remove without execution, retained downloads, duplicate/changed files, invalid IDs, Flatpak scope/ref/branch retention, exact Debian update architecture, provider failure isolation, stale plans, protected Debian removals, classic Snap review, update limits, and transaction locking.
- 2 protocol tests against a private PackageKit D-Bus service using Debian 13's PackageKit 1.3.1 client library. Covered Resolve, InstallPackages/RemovePackages simulation, legacy SetHints, signals, and error propagation. These are protocol tests, not tests of the real APT backend.
- Native headless UI smoke test using actual backend inventory: clicked Installed, received async inventory, typed an installed-software filter, and returned to Discover.
- AppImage desktop Exec escaping checked with the installed Cutefish desktop-entry parser, including spaces, backslashes, quotes, dollar signs, backticks and percent signs.
- Headless screenshot rendered and visually inspected at 1120 × 800. The shared preview image intentionally contains sample entries with operations disabled.
- Live read-only inventory: 880 installed Debian packages and 9 Snap entries. Live Snap catalog query returned results.
- Flatpak CLI availability, remotes and installed inventory checked. Flathub is configured system-wide; no Flatpak apps were installed. Search returned no matches with the current local catalog state.
- Generated Debian package inspected; no maintainer scripts or privileged helper are included. APT installation simulation resolved it with PackageKit and its client library, with no removals.

## Not verified

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
