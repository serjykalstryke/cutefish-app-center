# Architecture

`src/main.cpp` builds the native Cutefish views and invokes `backend/app_center_backend.py` as a separate unprivileged process. Requests are JSON on standard input; responses are newline-delimited progress events followed by a result. No shell is involved. Display strings never become commands.

The backend has four providers:

- Debian: `apt-cache` and `dpkg-query` for read-only search/inventory; PackageKit D-Bus transactions for simulations and modifications. PackageKit's installed client library converts enum values instead of assuming values from another version. Debian 13's `SetHints(as)` is supported, along with newer dictionary hints.
- Flatpak: CLI search/install/remove plus libflatpak GI inventory and reviewed update transactions. Explicit user/system scope, exact refs, origins and commits; no named installations yet.
- Snap: HTTP over the snapd Unix socket, `X-Allow-Interaction: true`, asynchronous change polling and explicit error handling.
- AppImage: AppImageHub feed discovery with a 24-hour cache and a browser handoff; a content-addressed personal library under `$XDG_DATA_HOME/cutefish-app-center/appimages/<sha256>`, with atomic metadata/desktop-entry writes. A bounded `unsquashfs` reader extracts only embedded metadata/icon bytes; the AppImage runtime and application are never executed during import. Existing metadata is migrated once when the library is read.

Search groups source choices using shared AppStream/desktop/common IDs, then unambiguous exact name/package aliases. Conflicting known identities and edition qualifiers prevent weak joins; unknown records cannot bridge two known applications. There is no fuzzy matching or application-name whitelist. Grouping affects the presentation of search results. The package source, scope, ref and immutable search variant key remain attached to each choice. Management inventory retains distinct installations.

Search ranks candidates before applying provider and global limits. Exact names/IDs lead, then category matches and names, keywords, summaries and description text. A small vocabulary maps common browser/editor/player queries to AppStream categories; app names and availability come from providers, not a curated application list. Category searches require category or short-purpose evidence and exclude helper packages and incidental long-description matches. Management inventory is untruncated, locally filtered and sorted with available updates first.

Flatpak search augments CLI results with desktop components from the existing per-scope, per-remote AppStream XML cache. Metadata candidates must join an exact available app ref (ID, architecture, branch, remote); each installation scope stays distinct. Legacy `desktop` components are accepted alongside `desktop-application`, while add-ons remain excluded. Debian reads OS-only XML/DEP-11 catalogs with libappstream, resolves repository-cached icons before installation, and falls back to APT names/summaries on minimal systems. Its pool excludes Flatpak and local desktop-file sources; metadata never changes the Debian transaction identity. The appstream and apt-config-icons packages let normal APT refreshes maintain that catalog and icon cache.

Plans bind targets, operations, changes and permission notes with a fingerprint. Applying a plan recomputes it and rejects a mismatch. This guards stale UI state; it is not an authorization token. Polkit/package services enforce authorization independently. A per-user advisory lock prevents App Center from starting simultaneous modifications. Other package tools can still operate; package-manager locks remain authoritative.

## Next engineering milestones

1. Disposable Debian/Flatpak/Snap transaction tests: install, upgrade, remove, missing dependencies, package lock contention, failed downloads, authentication denial, held packages and restart requirements.
2. Refine application classification and cross-source identity mapping against more distributions and catalogs.
3. Extend libflatpak transactions to installs/removals, permission previews, cancellation and interactive authentication.
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


## Catalog, navigation and the 0.2 identity migration

The native controller tracks the selected page separately from the provider list
mode. App Catalog without a query shows a full-width browsing page; searches and
category/card selections retain the results-and-details view. Installed combines
software inventory and updates. Install from File owns file
review and the drop target, and About owns version, author and project links.
Global file drops and command-line files route to the same review flow.

Catalog is the sidebar/menu label and App Catalog is the landing-page heading.
Category and featured-app navigation retain their display names separately from
the provider query,
so source filtering and Reload preserve the section heading. Editing the query
clears that context. Results expose Back to App Catalog (also View/Alt+Left),
which stops a pending search debounce, clears query/source/browsing state, and
resets details before returning to the landing page.

The catalog loads in a separate asynchronous process and only renders while the
home page is still selected. A per-session cache avoids repeating that work on
navigation; Reload and mutations invalidate it. Its manual carousel is a small
editorial selection joined to exact advertised stable Flatpak refs or actual
Debian packages. Missing apps are omitted. This selection does not alter search
ranking, and startup does not query Snap Store or the AppImage feed.

The package, binary, data directory and repository are `cutefish-app-center`;
the desktop identity is `org.cutefish.AppCenter`. Debian replacement metadata
removes the older `cutefish-store` package. Before ordinary backend dispatch, a
locked, resumable migration validates legacy AppImage IDs, bytes and metadata,
then moves managed directories and rewrites only generated launchers/artwork
paths. Original downloads stay in place. A conflicting validated new import
keeps its newer metadata and retains the legacy copy as a backup. Changed
archives and unsafe symlinks are refused instead of silently adopted.


## Background result artwork

Snap search/inventory and AppImageHub results register provider-derived icon
locators in a personal cache. Lists only consult existing artwork; they never
wait for per-icon network requests. A separate native process asks for small
batches covering the visible rows and a little overscan, then streams individual
icon completions. Scrolling schedules another batch. A generation check and
process cancellation discard work from older searches/pages, independently of
selection details and package operations.

The icons operation accepts bounded opaque cache keys, not URLs or file paths.
Its source registry validates each locator against its hash. Public HTTPS
artwork uses the same bounded image validation, redirect policy and atomic
cache writes as detail images; installed Snap artwork comes from the exact
snapd Unix-socket icon endpoint. Four downloads run concurrently at most.
Existing files are reusable immediately and retained after offline refresh
failures. Missing or malformed icons preserve the generic fallback. Catalog
artwork does not install, launch or download an application binary.


## Unified software management and system updates

`library` returns the complete installed inventory; `update_inventory` returns
independent per-source update candidates and completion warnings. Explicit
refresh checks refresh PackageKit and enabled Flatpak remotes. The native
controller loads updates asynchronously, preserves explicit selection, and
filters cached data without invoking a solver on each keystroke. A source failure
keeps available inventory visible but disables Update All.

`install_key` includes Debian architecture or the full Flatpak scope/kind/ID/
architecture/branch/origin. Management never merges separate installations.
Debian applications require desktop AppStream evidence or a package-owned visible
launcher. Snap applications require an exported visible launcher and app type;
bases and services remain system components. Flatpak app refs and imported
AppImages are applications; runtime refs are system components and cannot launch.
No name-prefix blacklist determines application status. Runtime/base removals
are refused, while protected system-package updates remain available.

`plan_all_updates` checks every configured source before preparing any changes.
PackageKit simulates UpdatePackages using exact IDs and architectures; held or
blocked candidates are excluded and protected removals refused. libflatpak
resolves app/runtime updates and related extensions, then aborts on
ready-pre-auth before authorization or deployment. Snap lists explicit refresh
targets and revisions; supporting components are resolved by snapd at execution.
AppImages remain manual. All groups and their exact changes determine one
fingerprint. The native review includes groups hidden by current list filters.

`apply_all_updates` recomputes the entire plan under the mutation lock, rejects
changed targets/dependencies and uses the recomputed groups. Debian re-simulates
immediately before applying. Flatpak resolves the current remote commits through
its transaction and checks them against the reviewed operation identity before
and after authorization; required related installs retain their
original root target even if that root commit is current. Individual Flatpak
updates use the same review/apply machinery. New remotes and interactive remote
authentication are refused. Snap rechecks revisions and refreshes only reviewed
names. Execution proceeds Debian, system Flatpak, user Flatpak, Snap; the first
failure stops subsequent sources and reports completed and unattempted groups.
There is no cross-provider rollback. PackageKit restart signals distinguish
application restarts, session restarts and system restarts.

The libflatpak update flow follows the upstream
[transaction API](https://docs.flatpak.org/en/latest/libflatpak-api-reference.html).


## Application-centered search

Search is ranked before grouping. The backend deduplicates exact source records,
joins explicit identifiers first, and considers conservative lexical aliases
against that complete identity graph. Ambiguous aliases and competing matches
remain separate. ESR/beta/nightly/unstable/canary qualifiers distinguish weak
name matches; branches of one explicitly identified Flatpak app stay selectable.
Installed native packages missing catalog metadata can use their package-owned
visible desktop launcher as identity evidence. Non-application Debian packages
remain independently searchable rather than alternative installers for an app.

The 300-result bound applies to application groups; every variant in an included
group is retained. Each variant carries an application presentation key, common
title/summary/artwork, available-provider labels and a source key derived from
its exact original target. Existing installations sort first, then stable
choices and Debian/Flatpak/Snap/AppImage order. Source completion order does not
set the application's position. The native card displays the common title and
providers, while its dropdown shows the exact source and installation status.
Duplicate labels include package/ref architecture to disambiguate choices.

Selection is remembered per application, with optional persistence across sessions
and a configurable format order in Settings. [Preference storage](PREFERENCES.md)
describes selection precedence and the shared JSON format. Changing source
cancels the old detail process and only its current generation can render.
The source-specific publisher, version, permissions, screenshots and actions
remain attached to that selected target. Operations use the exact installation
identifier for that choice.


Update All streams indexed source events for active, completed, failed and
skipped groups. The progress dialog binds indices to the reviewed source order.
PackageKit dispatches property changes while waiting for the method reply, so
reported authentication and lock waits can appear immediately. Snap uses the
active task's progress and Flatpak uses transaction operation progress. When a
provider has no measurable progress, the active row shows an indeterminate bar.
If a service stops mid-operation, rows without a confirmed result show an
unknown outcome. The result retains restart notices even if a later source
fails or Debian reports an error after applying changes.


Debian update discovery cross-checks PackageKit's exact candidate IDs against
installed dpkg versions. Debian version ordering determines eligibility.
Repository entries at the installed version are treated as replacement builds
for reinstall rather than upgrades. A valid review must contain changes, and
the installed package must reach the reviewed version before the app reports
success. Both single updates and Update All use these checks.

## Catalog release policy and Debian source helper

`Preferences` persists per-user Flatpak/Snap catalog choices. The backend filters
provider alternatives before application identity grouping. Snap beta lookups use
a bounded, short-lived metadata cache; plan/apply always revalidate channel and
revision with snapd. Installed inventories, updates and package targets are not
filtered by catalog preferences.

`backend/debian_releases.py` owns read-only source analysis, deterministic reviews,
source generation, integrity checks and transactional writes. The normal backend
only reads it. `/usr/libexec/cutefish-app-center/debian_sources_helper.py` is the
fixed root entry point registered by `org.cutefish.app-center.manage-debian-sources`
in `data/org.cutefish.AppCenter.policy`. Only active-session administrator
authorization permits execution; there is no unattended or inactive grant. The
helper accepts exactly `release` and `fingerprint`, a bounded JSON line, and no
arguments. It never installs packages, runs arbitrary commands or accepts caller
paths. The installed module/script/policy are root-owned package files.

Original source backups live under `/var/lib/cutefish-app-center/source-backups`
with 0700 directory/0600 files. The root-owned 0644 journal/state JSON contains
source paths and hashes needed for unprivileged review, not source file contents.
A source hash, permission or managed-state mismatch blocks mutation. Source
updates are written atomically; rollback restores prior bytes on a reported
failure, and the durable journal supports explicit restoration after interruption.
Original backups are retained after restoration. Tests use isolated filesystem
roots; the installed helper has no root override.
