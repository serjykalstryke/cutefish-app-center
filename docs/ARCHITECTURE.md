# Architecture

`src/main.cpp` builds the native Cutefish views and invokes `backend/store_backend.py` as a separate unprivileged process. Requests are JSON on standard input; responses are newline-delimited progress events followed by a result. No shell is involved. Display strings never become commands.

The backend has four providers:

- Debian: `apt-cache` and `dpkg-query` for read-only search/inventory; PackageKit D-Bus transactions for simulations and modifications. PackageKit's installed client library converts enum values instead of assuming values from another version. Debian 13's `SetHints(as)` is supported, along with newer dictionary hints.
- Flatpak: machine-readable columns from the supported Flatpak CLI, explicit `--user`/`--system`, exact refs and remote names. No named installations yet.
- Snap: HTTP over the snapd Unix socket, `X-Allow-Interaction: true`, asynchronous change polling and explicit error handling.
- AppImage: AppImageHub feed discovery with a 24-hour cache and a browser handoff; a content-addressed personal library under `$XDG_DATA_HOME/cutefish-store/appimages/<sha256>`, with atomic metadata/desktop-entry writes. A bounded `unsquashfs` reader extracts only embedded metadata/icon bytes; the AppImage runtime and application are never executed during import. Existing metadata is migrated once when the library is read.

Source entries only merge when a shared AppStream identity is known. The package source, scope and ref remain attached to each variant throughout the UI.

Search ranks candidates before applying provider and global limits. Exact names/IDs lead, then category matches and names, keywords, summaries and description text. A small vocabulary maps common browser/editor/player queries to AppStream categories; app names and availability come from providers, not a curated application list. Category searches require category or short-purpose evidence and exclude helper packages and incidental long-description matches. Installed/Updates retain their inventory ordering and local filtering.

Flatpak search augments CLI results with desktop components from the existing per-scope, per-remote AppStream XML cache. Metadata candidates must join an exact available app ref (ID, architecture, branch, remote); each installation scope stays distinct. Legacy `desktop` components are accepted alongside `desktop-application`, while add-ons remain excluded. Debian optionally reads XML catalogs and falls back to APT names/summaries on minimal systems; AppStream YAML support is still a future milestone.

Plans bind targets, operations, changes and permission notes with a fingerprint. Applying a plan recomputes it and rejects a mismatch. This guards stale UI state; it is not an authorization token. Polkit/package services enforce authorization independently. A per-user advisory lock prevents this store from starting simultaneous modifications. Other package tools can still operate; package-manager locks remain authoritative.

## Next engineering milestones

1. Disposable Debian/Flatpak/Snap transaction tests: install, upgrade, remove, missing dependencies, package lock contention, failed downloads, authentication denial, held packages and restart requirements.
2. Add AppStream YAML/libappstream support, app-only browsing, reliable cross-source identity mapping and installed-app launching through the Cutefish application registry.
3. Replace CLI Flatpak transactions with libflatpak for complete dependency/permission previews, structured progress, cancellation and robust EULA handling.
4. Add persistent transaction records, source settings and AppImage direct-download support with signature/hash verification and publisher update metadata.
5. Integrate localization, accessibility review, keyboard/focus testing and CI against a pinned toolkit version.

## Reference APIs

- [Cutefish toolkit](https://github.com/cutefishos/cutefish-toolkit)
- [PackageKit transaction interface](https://www.freedesktop.org/software/PackageKit/doc/dbus-org.freedesktop.packagekit1.Transaction.html)
- [Flatpak command reference](https://docs.flatpak.org/en/latest/flatpak-command-reference.html)
- [AppStream catalog categories and keywords](https://www.freedesktop.org/software/appstream/docs/chap-CatalogData.html)
- [snapd REST API](https://snapcraft.io/docs/snapd-api)
- [AppImage updates](https://docs.appimage.org/packaging-guide/optional/updates.html)


AppImage metadata reads use the system's `unsquashfs` under `prlimit`, with output, memory, CPU and wall-time limits. Only display metadata is copied from the embedded desktop file; its Exec, actions, D-Bus activation and file associations are not imported. The generated launcher always runs the managed AppImage path. Unsupported/malformed icons fall back to the generic icon. Type-1 metadata and runtimes whose SquashFS payload starts beyond the first 16 MiB currently use that fallback.


## Application details and launching

A separate cancellable backend process reads app details on demand. Responses carry a selection generation so a completed request cannot replace a newer selection. Source/ref identity is retained when metadata enriches a record. AppStream XML supplies developer, license, HTTPS homepage, cached icons and screenshot metadata; APT supplies package descriptions/maintainers, Snap supplies its publisher/media fields, and AppImageHub supplies catalog artwork and separately labeled catalog authors. Missing metadata remains an explicit fallback.

Artwork downloads accept public HTTPS URLs and validated image content, with byte/dimension bounds, bounded SVG decompression, timeouts and atomic cache writes. Existing cached images remain usable offline. Gallery images are decoded asynchronously by the native toolkit. No catalog Exec value becomes a launch command.

Open rechecks installed state. Debian launchers come only from that package's application files; Snap launchers come from its exported desktop entries; imported AppImages use the generated managed launcher. These desktop entries launch through Gio. Flatpak uses its selected installation, architecture and branch after confirming its exact origin/ref is installed. Libraries, services and catalog-only listings have no Open action.

The native Menu tree is registered through Application::setMainMenu, with Application/Help menu roles. The application menu belongs to the configured display name; the status bar owns its presentation. Window controls occupy the full-height sidebar, which has a square internal boundary; detail cards retain their own corner radius.
