# Cutefish Store

<img src="data/org.cutefish.Store.svg" alt="Cutefish Store icon" width="96" height="96">

A native software manager for the current Cutefish desktop on Debian 13,
with Debian, Flatpak, Snap and AppImage providers. Shared development is intended
for Cutefish and NordOS. This is an independent early prototype.

## Build from source on Debian 13

The repository contains source code. Generated `.deb` packages are deliberately
excluded from Git; the steps below build your own package.

### 1. Install the current Cutefish toolkit

You need a working current Cutefish session and the native C++20/Skia/Wayland
`cutefish-toolkit`, including its headers, shared libraries and
`CutefishToolkitConfig.cmake`. Follow the official
[Cutefish build guide](https://github.com/cutefishos/getting-started) if those
are not already installed. The store build does not download or build the
toolkit itself.

The tested Cutefish Debian package includes the toolkit's development files.
If CMake cannot find `CutefishToolkit`, check that those files are installed
and that you are using the current native toolkit.

### 2. Install the store's build and runtime dependencies

```sh
sudo apt update
sudo apt install build-essential cmake git python3 python3-gi \
    packagekit libpackagekit-glib2-18 xdg-utils squashfs-tools util-linux \
    libfuse2t64 dbus
```

The Cutefish session supplies the graphical Polkit agent for administrator
prompts. `squashfs-tools` and `util-linux` read embedded AppImage metadata;
`libfuse2t64` supports older AppImage runtimes that need `libfuse.so.2`.

Install optional providers if you want to use them:

```sh
sudo apt install flatpak snapd
```

The store uses existing APT sources, Flatpak remotes and snapd configuration;
it does not add repositories automatically. Configure a Flatpak remote such
as Flathub using its [official setup instructions](https://flathub.org/setup).

### 3. Clone and compile

```sh
git clone https://github.com/serjykalstryke/cutefish-store.git
cd cutefish-store
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr
cmake --build build --parallel 2
```

### 4. Run without installing

Run these commands from the repository directory inside your Cutefish session:

```sh
CUTEFISH_STORE_BACKEND="$PWD/backend/store_backend.py" \
CUTEFISH_STORE_BRANDING="$PWD/data/branding.json" \
./build/cutefish-store
```

For a visual preview with sample entries and software operations disabled:

```sh
./build/cutefish-store --preview
```

The backend/branding overrides are development settings. The normal installed
app uses its files under `/usr/libexec` and `/usr/share`.

### 5. Build and install a local Debian package

```sh
python3 scripts/package.py build/cutefish-store \
    --output cutefish-store_0.1.2_amd64.deb
sudo apt install ./cutefish-store_0.1.2_amd64.deb
cutefish-store
```

The current packaging script targets **Debian 13 amd64** and declares the
required Cutefish toolkit revision and runtime packages. APT resolves those
dependencies. Installing through the package also adds the launcher, store
icon, AppStream metadata and local-file associations.

For development, you can instead install the compiled project directly:

```sh
sudo cmake --install build
```

That method does not track installed files with dpkg or install dependencies;
the prerequisite packages above must already be present. Use the `.deb` for
normal system installation.

## Using the store

- **Discover:** search configured Debian, Flatpak and Snap sources, plus the
  community AppImage catalog.
- **Installed:** inspect and remove installed software. Debian inventory
  includes system packages, so review dependency changes before confirming.
- **Updates:** apply individual updates reported by configured providers.
- **Open file…** or drag a local `.deb`/AppImage onto the window to review it.

```sh
cutefish-store ~/Downloads/example.deb
cutefish-store ~/Downloads/Example.AppImage
```

Matching Debian AppStream and Flatpak IDs share a detail page with a source
selector. Flatpak scope, architecture, branch and remote remain attached to
each choice. Search excludes Flatpak runtime extensions.

AppImage search uses the [AppImageHub feed](https://appimage.github.io/feed.json),
cached for 24 hours. It opens a download page in your browser; download the
file, then import it in the store. Catalog presence does not verify a publisher
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
dbus-run-session -- python3 tests/test_packagekit_protocol.py -v
```

The protocol tests use a private fake PackageKit service and do not modify the
system package database. Archive tests use `mksquashfs` and `unsquashfs` from
`squashfs-tools`. CI runs these checks on Debian 13.

Build and run the native headless integration test:

```sh
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX=/usr -DSTORE_BUILD_NATIVE_TEST=ON
cmake --build build --parallel 2
mkdir -p work
CUTEFISH_STORE_BACKEND="$PWD/backend/store_backend.py" \
./build/cutefish-store-native-smoke
```

Real install/update/remove testing belongs on a disposable system. See the
[validation notes](docs/VALIDATION.md) for results and their limits.

## Current limits and troubleshooting

This is a first version. AppImage downloads/updates are manual, named system
Flatpak installations are unsupported, and Debian metadata reads AppStream
XML rather than YAML. There is no update-all, repository editor, transaction
history, permission editor, ratings or screenshots yet. Search/display limits
are described in [architecture notes](docs/ARCHITECTURE.md).

Debian transactions use PackageKit simulation, review, and normal Polkit
authorization. Essential/protected removals are refused. Flatpak/Snap services
handle their own runtime dependencies; their review is not a full dependency
or download-size simulation. Local Debian packages and AppImages should come
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
