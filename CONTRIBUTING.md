# Contributing

This is an independent native Cutefish software-management project intended for use
in both Cutefish and NordOS. Upstream adoption has not been agreed with Cutefish.

Please keep package providers, authorization, transaction previews and general
UI improvements shared. Distribution branding belongs in configuration and
packaging. See [NordOS integration](docs/NORDOS.md).

For a bug report, include the App Center version, Debian/Cutefish versions, software
source, installation scope and visible error. Remove personal paths or other
private details from logs. Do not attach credentials.

Before submitting a change:

1. Run `python3 tests/test_backend.py -v`, `python3 tests/test_search.py -v`, `python3 tests/test_details.py -v`, `python3 tests/test_discover.py -v`, `python3 tests/test_debian_catalog.py -v` (requires `gir1.2-appstream-1.0`), `python3 tests/test_catalog_icons.py -v`, and `python3 tests/test_packaging.py -v`.
2. If touching Debian transactions, run
   `dbus-run-session -- python3 tests/test_packagekit_protocol.py -v` with
   `python3-gi`, `dbus` and `libpackagekit-glib2-18` installed.
3. Build native UI changes against the current Cutefish toolkit and check
   the affected flow. `-DAPP_CENTER_BUILD_NATIVE_TEST=ON` builds the inventory, details, home-page and asynchronous-icon headless smoke tests.
4. Use a fresh build directory and the system compiler for a release. The package script must pass its runtime linkage check against the target toolkit.
5. Test package mutations on a disposable Debian 13 system. Distinguish mock or
   protocol tests from real install/update/remove results in your pull request.

Preserve existing license notices. New project code uses BSD-3-Clause. Keep
commits focused, and explain the user-visible change and relevant validation.
