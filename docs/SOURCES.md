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

Adding/editing Debian source addresses, suites, components or signing keys is not
implemented. A universal “stable/beta/nightly” setting would not describe Debian
sources correctly. Use the distribution’s source configuration for those edits;
App Center does not rewrite APT files or run a custom privileged helper.

## Flatpak

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

Snap uses the Snap Store. On an app card, **Release channel** lists the tracks and
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
