# Software sources and release channels

Open **Settings → Software Sources**. Each provider reports its own availability,
so a stopped service or an unavailable repository does not hide the other formats.
Use **Reload Sources** to read configuration again. Every source mutation has a
review before it is applied; administrator authorization stays with the existing
system services. Installed software is retained when a source is disabled.

## Native Debian repositories

App Center lists repositories reported by PackageKit and enables/disables those
exact configured entries. This affects all users. Source IDs are retained exactly
and re-read before and after the change. PackageKit’s APT backend controls which
entries can be changed and reports any authorization or backend error.

The **Debian release** dropdown offers **Original system configuration**,
**Debian Stable**, **Debian Testing** and **Debian Unstable**. Selecting a different
release first opens a review showing the exact source files, generated archive
entries, signing keyring, restoration behavior and operating-system implications.
The dropdown changes only after a successful authorized commit. No package is
installed or downgraded by switching sources. The catalog is then refreshed;
package changes remain separately reviewed through **Installed → Update All**.
Changing back to Stable or restoring sources does not downgrade packages.

Stable, Testing and Unstable follow Debian’s moving release aliases, including
future major-version transitions. The switcher recognizes official Debian archive hosts and Debian's standard
mirror-list files. It preserves enabled components, source-package types and
consistent architecture restrictions, uses canonical official HTTPS archives and
the dedicated Debian archive keyring, and backs up original active Debian
entries. Stable includes updates/security and previously configured backports.
Testing uses testing and testing-security; Unstable has neither a separate
security suite nor stable-updates/backports. Existing third-party repositories
and disabled original entries are retained. They may not support the new release.
APT pinning and held packages remain system policy; App Center does not rewrite
them or promise a complete distribution upgrade when the solver blocks changes.

A fixed installed Polkit helper performs these source edits after administrator
authorization. Its request accepts only an allowlisted release and reviewed
fingerprint, never paths, file contents or commands. It has a system-wide lock,
private durable backups and a journal, rechecks current files and verifies saved
results. A failed operation rolls back completed writes; an interrupted change
can restore the original configuration. Externally edited files or additional
active Debian entries are refused rather than overwritten. Managed entries use
the release dropdown instead of individual toggles. Unsupported custom source
options, untrusted keys, unsafe permissions and unrecognized mirrors require
manual source configuration. Custom repository address/key editing remains
outside this UI.

## Flatpak

The **Catalog release** dropdown chooses Stable or Beta / testing for search.
Configured stable/beta Flathub pairs appear as one source row per scope, following
this choice. Both remotes remain configured so installed apps can continue to
receive their own updates. A source outside the selected release can still be
managed, and adding a beta source does not select it automatically.

Account and system remotes are distinct. Add a source using a public HTTPS
`.flatpakrepo` address with an embedded signing key, or choose **Flathub (stable)**
or **Flathub Beta**. Select **Only my account** or **All users**. The review shows
the resulting repository URL, scope and SHA-256 of its signing-key data. Accept
only a source whose publisher you trust. HTTPS redirects, size limits and signing
key requirements are checked. Signature verification is explicitly enabled.

The file is fetched again before applying. Changed repository contents or source
state require a new review. The imported key and remote are handled by libflatpak;
no repository-supplied executable is run. Removing a source is allowed only when
no installed application or runtime uses it. Disable it instead if software must
remain installed. Named additional system installations are not supported yet.

After source changes, use **Refresh Flatpak Catalog** to fetch application metadata.
An app’s existing source dropdown preserves its remote, account/system scope,
architecture and branch. Adding a beta remote does not migrate stable installations
or guarantee that every publisher provides beta/nightly builds.

## Snap

If Flatpak or Snap support is absent, **Install Support** reviews installation of
the fixed Debian package `flatpak` or `snapd` through PackageKit. For an installed
but stopped Snap service, **Start Snap Support** requests starting `snapd.socket`
through systemd’s normal authorization. It does not alter boot-time service policy.

Snap uses the Snap Store. Its **Catalog release** dropdown selects Stable or Beta
for new search results. Beta searches include non-stable Store matches, verify
published channel maps and omit matches without a beta channel. Stable results
are never substituted for missing beta builds. Channel lookups are cached for ten
minutes and limited to the best 24 ranked matches per search; a broad search asks
the user to narrow the query. Failures remain visible. Installation reviews
always re-read the actual channel/revision, independently of this display cache.

On an app card, **Release channel** lists the tracks and
channels currently advertised for that snap. Stable, candidate, beta, edge and
publisher-specific tracks appear only where actually published. Developer-mode
snaps are not supported. Classic confinement is identified in the review.

For a new installation, choose a channel and click **Install**. For an installed
snap, selecting another channel exposes **Change Channel**. The review identifies
the requested channel and exact revision and warns about testing releases and
possible downgrades. Applying uses a Snap refresh with both the channel and reviewed
revision, then verifies the installed revision and tracking channel. New revisions,
changed installed state or withdrawn channels require another review.

A channel selection before installation is held in the current detail view. Once
installed, snapd persists the tracking channel and its automatic refreshes follow
that channel. App Center’s saved format/source preferences are separate from this
Snap refresh policy. Merely opening a dropdown never installs or switches software.

## AppImage

AppImages use the existing community catalog and publisher download pages. Import
local downloads with **Install from File**. App Center does not invent repository
channels or automatic update support for AppImages.

## Implementation and checks

Source mutations use the same per-user transaction lock as software operations.
Reviews are re-created and compared before mutation; operations verify actual saved
state afterwards. Source labels redact URL credentials and query parameters. Errors
remain visible and no failed transaction is presented as completed.

Tests cover private PackageKit D-Bus source transactions, trust/scope validation,
stale reviews, authorization errors, channel/revision selection and native UI flow.
Disposable Debian VM checks exercise real APT and libflatpak changes without editing
the development desktop’s repositories. See [validation](VALIDATION.md).
