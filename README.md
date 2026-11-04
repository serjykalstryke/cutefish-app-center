# Cutefish Store

<img src="data/org.cutefish.Store.svg" alt="Cutefish Store icon" width="96" height="96">

**Early native prototype · Debian 13 · shared development for Cutefish and NordOS.**

A native C++/Skia/Wayland application for **the current Cutefish desktop on Debian 13**, with an unprivileged Python provider layer. This targets the current `cutefish-toolkit`, not the older Qt/QML toolkit. It is an independent prototype, not an official Cutefish release.

The source is maintained at [serjykalstryke/cutefish-store](https://github.com/serjykalstryke/cutefish-store).
See [contributing](CONTRIBUTING.md), [NordOS branding/integration](docs/NORDOS.md),
and the [changelog](CHANGELOG.md).

## Try the packaged build

A locally packaged `cutefish-store_0.1.1_amd64.deb` is built for the installed Debian 13 Cutefish toolkit revision. From its download directory:

```sh
sudo apt install ./cutefish-store_0.1.1_amd64.deb
cutefish-store
```

APT installs the declared dependencies, including PackageKit. Installing the store does not install Flatpak apps, Snap apps, or add repositories. Flatpak and snapd are optional recommended providers. Existing remotes and package sources are used.

```sh
cutefish-store ~/Downloads/example.deb
cutefish-store ~/Downloads/Example.AppImage
cutefish-store --preview
```

`--preview` uses clearly labeled sample entries and disables software operations. Normal mode uses real sources. Select **Open file…**, drop a local file on the window, or use the file manager's **Open With** action. No default file associations are overwritten.

## What is implemented

| Source | Search | Installed inventory | Install/remove | Updates |
| --- | --- | --- | --- | --- |
| Debian | APT cache; AppStream XML names/icons when present | dpkg, including system packages | PackageKit with dependency simulation and a confirmation view | PackageKit; individual updates |
| Flatpak | Application refs from configured remotes; extensions excluded | Separate user and default system installations | Exact app/architecture/branch and remote, with scope preserved | Individual apps; dependencies handled by Flatpak |
| Snap | snapd store API | snapd | snapd API with desktop authorization | Individual refreshes; snapd also owns automatic refresh |
| AppImage | AppImageHub catalog plus imported library | Store-managed library | Import/copy and menu integration; remove managed copy | Download and import new versions manually |

Matching Debian AppStream IDs and Flatpak IDs share a detail page with a source selector. Entries without a shared identity stay separate; matching similar names is not sufficient to establish that two apps are the same.

AppImage discovery uses the [AppImageHub JSON feed](https://appimage.github.io/feed.json), cached for 24 hours. Catalog entries open a download page in your browser. Download the file there, then open it in the store to review and import it. Catalog presence does not verify a publisher or guarantee a current compatible download. Imported-file management works without the catalog.

**Refresh Debian catalog** downloads repository metadata through PackageKit. **Refresh Flatpak catalog** updates AppStream metadata for configured user/default system remotes. Snap queries its service directly. Provider failures appear separately so the remaining inventory stays available.

## Local packages and transaction behavior

- Debian repository operations require trusted packages. Local `.deb` files are inspected with `dpkg-deb`, hashed, simulated and explicitly reviewed. Local packages may run administrator installation scripts. PackageKit resolves dependencies and requests authorization through the desktop's Polkit agent.
- Before applying Debian changes, the dependency plan is computed again. A changed plan requires another review. Essential/protected package removals are rejected. No automatic autoremove or purge is requested.
- Flatpak permissions are shown before installation. Runtime/extension transactions remain Flatpak's responsibility. Removing an app retains its data.
- Classic Snap confinement is called out in the review; developer-mode installation is rejected. Stable is used for new installs. Removing a snap uses snapd's normal snapshot behavior.
- AppImage imports check ELF/AppImage magic, copy and verify the file, make the managed copy executable, and create an escaped desktop entry. **Import does not execute the AppImage.** Header checks do not establish publisher trust. Removing the managed copy preserves the original download and app data.
- One mutation runs at a time across store instances. Closing the window is blocked while it is applying changes. Package-manager services own their own locks and authorization; the UI never runs as root.

## Current limits

This is a first version, not a production-ready replacement for a mature software center.

- AppImage catalog discovery opens download pages; it does not download/install directly or update automatically. Existing unmanaged AppImages are not scanned automatically.
- No ratings/screenshots, repository editor, Flatpak permission editor, Snap channel selector, update-all, restart scheduling, transaction history or app launching from the store.
- Debian fallback search includes packages/libraries. AppStream XML is supported; Debian YAML catalogs are not yet read. A rich app-only catalog is a next step.
- Only the default system Flatpak installation and the user's installation are supported; named system installations are not included.
- Flatpak and Snap reviews show the app and access notes, not a complete dependency/download-size simulation. Upstream services may ask for licensing, keys or media that this version reports as an error instead of resolving interactively.
- Each provider search is limited to 100 results, and displayed inventory to 300 entries. Installed-software search narrows the full Debian inventory before display.
- PackageKit simulation and application are separate transactions, so external package managers can change the system between them. The service's own transaction checks still apply.
- The desktop user confirmed real native Debian and Snap application installs with 0.1.0. The 0.1.1 Flatpak fix has a live metadata/review check and mocked apply regression test; a real end-to-end Flatpak install still needs confirmation. Upgrades, removals and recovery paths need disposable-system validation before wider distribution.

## Build

Install the current Cutefish toolkit development package plus `cmake`, a C++20 compiler and standard build tools. On this system the toolkit headers and CMake configuration ship in `cutefish-toolkit`. Runtime requirements are `python3`, `python3-gi`, `xdg-utils`, `packagekit`, `libpackagekit-glib2-18`, and a desktop Polkit agent. Flatpak and snapd are optional.

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr
cmake --build build -j2
sudo cmake --install build
```

To run an uninstalled binary, point it to the provider script:

```sh
CUTEFISH_STORE_BACKEND="$PWD/backend/store_backend.py" ./build/cutefish-store
```

The backend override is a development feature, not a privilege boundary. The backend itself stays unprivileged. All package mutations are delegated to authenticated system services or the scoped Flatpak command.

## Verification

```sh
python3 tests/test_backend.py -v
dbus-run-session -- python3 tests/test_packagekit_protocol.py -v
```

The protocol tests use a private fake PackageKit service and the installed PackageKit client library. They do not touch the real system package service. `tests/native_smoke.cpp` checks native controls, async installed inventory, filtering and navigation using the toolkit's headless input API. Compile it like `src/main.cpp`, then run it with `CUTEFISH_STORE_BACKEND` set. Create a `work/` directory in the current working directory for its screenshot (`work/installed-smoke.png`).

See [validation notes](docs/VALIDATION.md) for the actual checks and limits of this build.

To package a locally built executable:

```sh
python3 scripts/package.py build/cutefish-store --output cutefish-store_0.1.1_amd64.deb
```

Automated CI runs backend and private D-Bus protocol tests on Debian 13.
Native toolkit builds and real package transactions are separate validation steps.

License: BSD-3-Clause.
