# Shared development and NordOS integration

Keep one application codebase. The default project name is Cutefish Store;
this repository is independent until Cutefish agrees to upstream adoption.
NordOS can ship the same executable and providers with different branding.

## Branding available now

The native window reads `/usr/share/cutefish-store/branding.json`:

```json
{
  "display_name": "Nord Software",
  "tagline": "Made for NordOS",
  "distribution_label": "NordOS",
  "icon": "org.cutefish.Store"
}
```

For an uninstalled preview:

```sh
CUTEFISH_STORE_BRANDING=/path/to/nordos-branding.json ./build/cutefish-store --preview
```

The JSON changes the window/header name, sidebar tagline and distribution
label and sidebar icon. NordOS packaging should also customize the desktop-entry Name/Comment,
icon artwork and AppStream display metadata. Those assets are intentionally
separate from provider logic. The stable `org.cutefish.Store` application ID
and `cutefish-store` package name currently remain the same; the two branded
packages should replace each other, not be co-installed.

## Release integration

Pin a tested release or commit of this repository in NordOS's component
inventory, then build it in the NordOS packaging pipeline. Use a NordOS package
revision such as `0.1.1-1+nordos1` for distribution-specific packaging.

Keep NordOS's branding assets in its distribution packaging. Do not have two
packages both own the same branding file; either generate it while building
the NordOS store package or add a properly designed configuration override
mechanism before shipping a separate branding package.

Source enablement, featured apps and provider preference configuration are
future work. The current app uses the system's existing APT sources, Flatpak
remotes and snapd service. It does not add repositories automatically.

A downstream code fork is only needed for substantial changes that cannot be
shared. General fixes should continue to be proposed to the shared project.
NordOS assistant integration should call a future stable transaction API with
visible review and normal system authorization; the current JSON provider
protocol is an internal implementation detail, not a stable public API.
