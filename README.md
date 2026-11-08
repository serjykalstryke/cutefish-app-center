# Cutefish App Center

<img src="data/org.cutefish.AppCenter.svg" alt="Cutefish App Center icon" width="96" height="96">

A native software manager for the current Cutefish desktop on Debian 13,
with Debian, Flatpak, Snap and AppImage providers. Shared development is intended
for Cutefish and NordOS. Created by David Stinnett. This is an independent community project.

## Upgrading from Cutefish Store

The application is now **Cutefish App Center**, with repository and package name
`cutefish-app-center`, desktop ID `org.cutefish.AppCenter`, and the command
`cutefish-app-center`. Installing the new `.deb` replaces the older
`cutefish-store` package through APT. Close the old app before upgrading.

The first backend request migrates managed AppImage imports from
`$XDG_DATA_HOME/cutefish-store` to `$XDG_DATA_HOME/cutefish-app-center`, updates
the generated menu entries and artwork paths, and preserves original downloads.
The migration can resume after interruption and refuses changed archives or
an active transaction in the old app. The old name remains only in migration,
package replacement metadata and historical license notices.

If you already cloned the repository, update its remote:

```sh
git remote set-url origin https://github.com/serjykalstryke/cutefish-app-center.git
```

## Build from source on Debian 13

The repository contains source code. Generated `.deb` packages are deliberately
excluded from Git; the steps below build your own package.

### 1. Install the current Cutefish toolkit

You need a working current Cutefish session and the native C++20/Skia/Wayland
`cutefish-toolkit`, including its headers, shared libraries and
`CutefishToolkitConfig.cmake`. Follow the official
[Cutefish build guide](https://github.com/cutefishos/getting-started) if those
are not already installed. The App Center build does not download or build the
toolkit itself.

The tested Cutefish Debian package includes the toolkit's development files.
If CMake cannot find `CutefishToolkit`, check that those files are installed
and that you are using the current native toolkit.

### 2. Install App Center's build and runtime dependencies

```sh
sudo apt update
sudo apt install build-essential cmake git python3 python3-gi \
    packagekit libpackagekit-glib2-18 xdg-utils squashfs-tools util-linux \
    libfuse2t64 dbus appstream gir1.2-appstream-1.0 gir1.2-flatpak-1.0 apt-config-icons
sudo apt update
```

The Cutefish session supplies the graphical Polkit agent for administrator
prompts. `squashfs-tools` and `util-linux` read embedded AppImage metadata;
`libfuse2t64` supports older AppImage runtimes that need `libfuse.so.2`.
`appstream`, its Python bindings and `apt-config-icons` provide Debian's
application catalog and icons before apps are installed. Run `sudo apt update`
after installing these dependencies to fetch that metadata and icon cache.
`gir1.2-flatpak-1.0` supplies structured Flatpak inventory and update transactions.

Install optional providers if you want to use them:

```sh
sudo apt install flatpak snapd
```

App Center uses existing APT sources, Flatpak remotes and snapd configuration;
it does not add repositories automatically. Configure a Flatpak remote such
as Flathub using its [official setup instructions](https://flathub.org/setup).

### 3. Clone and compile

```sh
git clone https://github.com/serjykalstryke/cutefish-app-center.git
cd cutefish-app-center
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr \
    -DCMAKE_CXX_COMPILER=/usr/bin/g++
cmake --build build --parallel 2
```

Use the installed system compiler with its complete development packages.
Avoid mixing headers, static archives and libraries from a partially extracted
compiler toolchain. When changing compilers or upgrading the Cutefish toolkit,
configure a fresh build directory (for example `-B build-clean`) and build there.

### 4. Run without installing

Run these commands from the repository directory inside your Cutefish session:

```sh
CUTEFISH_APP_CENTER_BACKEND="$PWD/backend/app_center_backend.py" \
CUTEFISH_APP_CENTER_BRANDING="$PWD/data/branding.json" \
./build/cutefish-app-center
```

For a visual preview with sample entries and software operations disabled:

```sh
./build/cutefish-app-center --preview
```

The backend/branding overrides are development settings. The normal installed
app uses its files under `/usr/libexec` and `/usr/share`.

### 5. Build and install a local Debian package

```sh
python3 scripts/package.py build/cutefish-app-center \
    --output cutefish-app-center_0.3.5_amd64.deb
sudo apt install ./cutefish-app-center_0.3.5_amd64.deb
cutefish-app-center
```

The packaging script verifies shared C++ runtime linkage and checks that all
runtime libraries and symbols resolve on the build system before writing the
package. You can run only that check with
`python3 scripts/package.py build/cutefish-app-center --check-only`.

The current packaging script targets **Debian 13 amd64** and declares the
required Cutefish toolkit revision and runtime packages. APT resolves those
dependencies. Installing through the package also adds the launcher, application
icon, AppStream metadata and local-file associations.

For development, you can instead install the compiled project directly:

```sh
sudo cmake --install build
```

That method does not track installed files with dpkg or install dependencies;
the prerequisite packages above must already be present. Use the `.deb` for
normal system installation.

## Using App Center

- **Catalog:** browse a featured-app carousel and application categories, or
  search configured Debian, Flatpak, Snap and AppImage sources. Selecting a card
  opens the existing search-and-details view so you can compare software sources.
  The main page is titled **App Catalog**. Opening a category uses its name as
  the heading, while a new text search shows **Search Results**. **Back** beside
  the heading returns to App Catalog and clears the query and source filter.
  The same action is available in the View menu and through Alt+Left.
- **Installed:** manage installed apps and updates together. Applications appear
  by default, with available updates first. Choose **All software** to include
  libraries, services and runtimes, or **Updates only** to narrow the list.
  **Check for Updates** refreshes configured sources. **Update All** reviews
  every source, including Debian system packages, Flatpak runtimes and Snap
  bases; its count and scope are independent of the visible filters.
- **Install from File:** drag a `.deb` or AppImage onto the page, or choose a
  file to review before installing. File drops elsewhere in the window also open
  this page. Ctrl+O opens the native file chooser.
- **About:** view the app version, David Stinnett’s author credit, license and
  project links. The application-name menu opens the same page.

```sh
cutefish-app-center ~/Downloads/example.deb
cutefish-app-center ~/Downloads/Example.AppImage
```

Search shows one entry per application, with its available formats listed on
the card. Use the **Software source** dropdown on the detail card to choose
Debian, Flatpak, Snap or AppImage. App Center selects an existing installation
first. For a new app it prefers Debian, then Flatpak, Snap and AppImage. The
dropdown shows availability and installation status and remembers your choice
when you return to that application during the session.

Common catalog/desktop identifiers join packages for the same application.
Exact name/package aliases fill metadata gaps only where they do not conflict
with other known identities. Chrome and Chromium, ESR and nightly editions, and
unrelated apps with the same name remain distinct. Missing or ambiguous
metadata can still leave separate entries.

The application title stays consistent when switching sources. Publisher,
version, screenshots, installation status and actions belong to the selected
source. Flatpak scope, architecture, branch and remote remain attached to each
choice. Installed retains separate installations for management, and Update All
continues to cover every configured provider. Search excludes Flatpak runtimes.

In Installed, application classification uses AppStream desktop metadata or
visible exported launchers, rather than package-name rules. Separate Flatpak
scopes and branches and Debian architectures remain separate installations.
Held or blocked updates are identified and excluded from Update All. AppImages
remain manually updated through their publishers.

Update All shows the proposed changes before **Apply Updates**. Canceling the
review applies nothing. If a source cannot be checked, the list remains usable
and Update All waits until that source is available. After you confirm, the
progress window shows each source and the steps its package manager reports.
Keep App Center open while updates are running. The result keeps completed
sources, failures, sources still to update, and restart or sign-in notices
together. After a failure, check for updates again to review the remaining work.

Select an app to load its full description, publisher, versions and license
where provided. Catalog artwork appears in a screenshot gallery; use the
arrows to browse and **Enlarge…** for a larger view. Artwork is cached, and
offline or missing screenshots do not block package reviews. **Project website**
opens the HTTPS homepage supplied by the software source.

Installed apps with launchers show **Open** beside their management action.
App Center checks the selected installation again before opening it. Debian
packages without a desktop launcher, Snap services and catalog-only AppImages
do not show Open. AppImage catalog authors are labeled separately from
upstream publishers; a verified-publisher label is shown only when Snap
explicitly reports verification.

Cutefish’s top bar exposes the application-name menu plus **File**, **View**,
**Software** and **Help**. Open File, Search, Reload and Quit use Ctrl+O, Ctrl+F,
Ctrl+R and Ctrl+Q (the desktop’s Command key also maps to Ctrl). The sidebar
continues to the top of the window with a square internal edge.

Navigation, category and file-import symbols follow the live Cutefish light/dark
text palette. Category artwork ships with the app, so it does not depend on
which icons the system theme provides. Application logos retain their original
colors.

Search ranks exact app names and identifiers first, followed by app categories,
names, keywords and summaries. Queries such as **web browsers**, **image editors**,
**text editors** and **media players** recognize their category and common aliases.
The Catalog categories use these same searches. Broad category searches filter
incidental description matches and helper packages; exact package names still
find libraries and other technical packages.

Search results come from your configured sources and are ranked independently
of the featured selection. App Catalog presents a small editorial selection of
common desktop apps only when they are available in configured local Debian
or Flatpak catalogs. Its carousel does not rotate automatically. Flatpak category search uses its existing local AppStream catalog and
checks exact available app refs. Debian reads its AppStream XML/DEP-11 YAML catalogs through libappstream,
including the repository icon cache. Icons appear before installation when
the configured source publishes them; packages without artwork keep a generic
icon. APT names and summaries remain a fallback on minimal installations. Catalog
quality and enabled sources affect which apps can be found.

Snap and AppImage catalog results load provider artwork in the background as
rows become visible. Cached icons appear immediately on later searches and
remain usable offline. Snap uses Store icon metadata for uninstalled apps and
snapd's local icon endpoint for installed apps when available. AppImageHub
supplies catalog artwork; imported AppImages keep their embedded icons. Missing
or invalid artwork keeps the generic icon and never blocks software management.
Only icons are fetched for browsing; AppImage downloads still open the browser.

AppImage search uses the [AppImageHub feed](https://appimage.github.io/feed.json),
cached for 24 hours. It opens a download page in your browser; download the
file, then import it in App Center. Catalog presence does not verify a publisher
or guarantee a compatible download.

AppImage import copies the file into a managed personal library and adds a
menu entry. Supported type-2 images supply their embedded name, description,
PNG/SVG artwork and window-matching metadata. Older imports refresh their
metadata when the store reads the library. Importing reads the archive without
executing the AppImage. If metadata is unavailable, a generic icon is used.
Removal preserves the original download and application data.

## Tests

From the repository directory:

```sh
python3 tests/test_backend.py -v
python3 tests/test_search.py -v
python3 tests/test_details.py -v
python3 tests/test_discover.py -v
python3 tests/test_debian_catalog.py -v
python3 tests/test_catalog_icons.py -v
python3 tests/test_packaging.py -v
python3 tests/test_management.py -v
dbus-run-session -- python3 tests/test_packagekit_protocol.py -v
```

The protocol tests use a private fake PackageKit service and do not modify the
system package database. Archive tests use `mksquashfs` and `unsquashfs` from
`squashfs-tools`. CI runs these checks on Debian 13.

Build and run the native headless integration test. It uses the host's actual
inventory and catalog; install Snap and configure system Flathub for its
`snapd` inventory filter and Brave/Chrome/Firefox discovery checks:

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX=/usr -DAPP_CENTER_BUILD_NATIVE_TEST=ON
cmake --build build --parallel 2
mkdir -p work
CUTEFISH_APP_CENTER_BACKEND="$PWD/backend/app_center_backend.py" \
./build/cutefish-app-center-native-smoke
./build/cutefish-app-center-details-smoke
./build/cutefish-app-center-home-smoke
./build/cutefish-app-center-icons-smoke
./build/cutefish-app-center-management-smoke
./build/cutefish-app-center-search-smoke
```

The search smoke test uses a private cross-provider fixture to check one app
card, exact source choices, installed-source preference, source-bound actions,
remembered selections and cancellation of outdated details. It never installs
or launches software. Its `--live` mode renders the actual Firefox search.

The management smoke test uses a private provider to check application filtering,
update sorting, global review scope, cancellation, partial-source errors and
restart messages. Its fixture apply writes a test marker only.
`./build/cutefish-app-center-management-smoke --live` renders the actual
Installed and All software lists without applying updates.

The icons smoke test covers delayed artwork, navigation while an icon request
is pending, small request batches and loading further rows on scroll. Its
`--snap` and `--appimage` modes render actual read-only catalog searches.
The home smoke test checks rendered navigation, category and file-import icons
while switching a live view between light and dark themes. It also covers
carousel navigation, category search, About credit
and file-drop review using a private provider. `./build/cutefish-app-center-home-smoke --live` renders all three pages with
the system catalog. The details smoke test uses a private provider fixture and never launches an
application or changes packages. `./build/cutefish-app-center-details-smoke --live`
uses the actual Firefox catalog and saves a rendered view to
`outputs/app-details.png`. Test assertions stay enabled
in Release builds.

Real install/update/remove testing belongs on a disposable system. See the
[validation notes](docs/VALIDATION.md) for results and their limits.

## Current limits and troubleshooting

If App Center reports a `symbol lookup error` after a toolkit update, rebuild
against the installed toolkit using a fresh build directory and the system
compiler, then recreate/reinstall the `.deb`. In particular, 0.2.3 corrects
`undefined symbol: _ZNSt8ios_base4Init20_S_synced_with_stdioE` in the earlier
provided binary. This was accidental partial static C++ runtime linkage;
it does not require downgrading Cutefish or replacing system libraries.


This is a first version. AppImage downloads/updates are manual, named system
Flatpak installations are unsupported. Debian artwork depends on the catalogs
and icon caches published by configured repositories. There is no repository
editor, transaction history, permission editor or ratings yet. Search/display limits
are described in [architecture notes](docs/ARCHITECTURE.md).

Debian transactions use PackageKit simulation, review, and normal Polkit
authorization. Essential/protected removals are refused. Flatpak updates use
libflatpak to review and recheck exact commits and required runtime changes;
new sources and interactive repository authentication are unsupported in this flow.
Flatpak installs/removals still use the CLI and do not provide the same full
dependency preview. Snap reviews list the selected refreshes; snapd resolves
supporting components when execution starts. Local Debian packages and AppImages should come
from a publisher you trust.

If an imported AppImage immediately exits, run the downloaded file in a
terminal to see its error. For `error loading libfuse.so.2`, Debian 13 needs:

```sh
sudo apt install libfuse2t64
```

Follow the [AppImage FUSE guidance](https://docs.appimage.org/user-guide/troubleshooting/fuse.html)
for remaining mount errors. The file manager's executable-file confirmation
is separate from the app menu entry.

See [contributing](CONTRIBUTING.md), [NordOS branding/integration](docs/NORDOS.md),
and the [changelog](CHANGELOG.md). License: BSD-3-Clause.
