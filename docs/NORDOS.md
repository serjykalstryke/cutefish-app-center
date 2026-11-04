# Shared development and NordOS integration

Keep one application codebase. The default project name is Cutefish App Center;
this repository is independent until Cutefish agrees to upstream adoption.
NordOS can ship the same executable and providers with different branding.

## Branding available now

The native window reads `/usr/share/cutefish-app-center/branding.json`:

```json
{
  "display_name": "Nord Software",
  "sidebar_name": "App Center",
  "author": "David Stinnett",
  "project_url": "https://github.com/serjykalstryke/cutefish-app-center",
  "distribution_label": "NordOS",
  "icon": "org.cutefish.AppCenter"
}
```

For an uninstalled preview:

```sh
CUTEFISH_APP_CENTER_BRANDING=/path/to/nordos-branding.json ./build/cutefish-app-center --preview
```

The JSON changes the window name, sidebar name, About credit/project links, distribution
label and sidebar icon. NordOS packaging should also customize the desktop-entry Name/Comment,
icon artwork and AppStream display metadata. Those assets are intentionally
separate from provider logic. The stable `org.cutefish.AppCenter` application ID
and `cutefish-app-center` package name currently remain the same; the two branded
packages should replace each other, not be co-installed.

## Release integration

Pin a tested release or commit of this repository in NordOS's component
inventory, then build it in the NordOS packaging pipeline. Use a NordOS package
revision such as `0.1.1-1+nordos1` for distribution-specific packaging.

Keep NordOS's branding assets in its distribution packaging. Do not have two
packages both own the same branding file; either generate it while building
the NordOS store package or add a properly designed configuration override
mechanism before shipping a separate branding package.

Source enablement, custom featured selections and provider preference
configuration are future work. The current app uses the system's existing APT sources, Flatpak
remotes and snapd service. It does not add repositories automatically.

A downstream code fork is only needed for substantial changes that cannot be
shared. General fixes should continue to be proposed to the shared project.
NordOS assistant integration should call a future stable transaction API with
visible review and normal system authorization; the current JSON provider
protocol is an internal implementation detail, not a stable public API.
