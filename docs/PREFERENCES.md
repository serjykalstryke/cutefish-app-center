# Application source preferences

Settings is available from the sidebar, application menu and Ctrl+,. It currently
controls format order, remembered application choices and stable/beta catalog
selection for Flatpak and Snap. Software Sources also manages repositories and
Debian release configuration through separate reviews. Background monitoring and
unattended installation remain separate milestones.

## Selection rules

1. Use an explicit remembered choice if that exact choice is currently available.
2. Otherwise, prefer an installed choice. When more than one format is installed,
   use the configured format order to select which one is shown first.
3. For applications with no installed choice, use the configured format order.
   Existing provider ordering breaks ties within a format.

The initial order is `deb`, `flatpak`, `snap`, `appimage`. A preference never makes
an unavailable format available. AppImage catalog choices retain their browser
download/import flow. Installed management and updates retain exact installation
targets and do not use this preference to migrate packages between providers.

The detail card's Use Default Source action removes one application's override.
Settings can clear all choices, turn persistence off, or restore default order
and remembering. Turning remembering off clears stored choices. Explicit choices
can still be used during the current session without being stored for the next.

## Storage

The private file is `$XDG_CONFIG_HOME/cutefish-app-center/preferences.json`, or
`~/.config/cutefish-app-center/preferences.json` when XDG_CONFIG_HOME is unset or
relative. Development/tests can override the full path with
`CUTEFISH_APP_CENTER_PREFERENCES`. Native tests always isolate this path.

```json
{
    "version": 1,
    "source_order": ["deb", "flatpak", "snap", "appimage"],
    "remember_choices": true,
    "application_choices": {},
    "catalog_releases": {"flatpak": "stable", "snap": "stable"}
}
```

This versioned format is internal to App Center. Application choice keys use the
grouped application identity; their values are exact variant keys already supplied
by search. Flatpak scopes, refs and remotes remain distinct. Missing keys use
defaults; unknown or duplicate format names are filtered and omitted supported
formats are appended. Choices unavailable in the current search are not applied.

Each change rereads the latest document under an advisory lock, preserves unrelated
and unknown fields, and atomically replaces the file after writing and syncing a
same-directory temporary file. Preference files and lock files are created with
0600 permissions. Read/write size is limited to 1 MiB. The lock is independent of
software transaction locks and requires no administrator privileges.

Malformed, unreadable and unsupported-version documents are left intact. Settings
shows a notice and disables edits until the user chooses Restore Defaults. Failed
writes do not change the in-memory preference order. An explicit source selection
can still apply for that session if persistence fails, with an error explaining
that it could not be saved. Opening Settings does not write a preference file.

## Catalog release selection

Software Sources has independent Flatpak and Snap dropdowns. Each defaults to
Stable. Flatpak Beta / testing includes beta, nightly and other explicitly named
testing branches/remotes. Snap Beta selects an actual published beta channel,
with latest/beta preferred when multiple tracks offer beta. Results without the
selected release are omitted before grouping. There is no stable fallback in a
beta search. Featured Flatpak recommendations follow the same selection.

These controls filter new catalog choices; they do not disable remotes, migrate
installed apps or filter installed/update inventories. A saved app source hidden
by this selection follows the normal unavailable-choice fallback. Once an app is
installed, its exact installation/update source continues to be used. A Snap
already on another channel exposes a separate Change Channel review.

The optional `catalog_releases` object retains only `flatpak` and `snap`, with
values `stable` or `beta`. Missing/unknown values use stable. Writes preserve
unrelated fields under the existing lock. Restore Defaults restores stable
catalogs along with format order and source choices; it does not alter Debian
sources. Debian release selection is system configuration and is not stored in
this per-user preference file.
