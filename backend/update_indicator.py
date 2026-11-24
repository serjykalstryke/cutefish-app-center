#!/usr/bin/python3
"""Run scheduled checks in the login session and expose updates in the status bar."""
import json
import os
from pathlib import Path
import sys

from gi.repository import Gio, GLib


APP_ID = 'org.cutefish.AppCenter'
WATCHER = 'org.kde.StatusNotifierWatcher'
ITEM_NAME = APP_ID + '.UpdateIndicator'
ITEM_PATH = '/StatusNotifierItem'
ITEM_INTERFACE = 'org.kde.StatusNotifierItem'
ICON = 'software-update-available-symbolic'
ITEM_XML = f'''<node>
  <interface name="{ITEM_INTERFACE}">
    <method name="Activate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="IconPixmap" type="a(iiay)" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
    <signal name="NewIcon"/>
    <signal name="NewTitle"/>
    <signal name="NewToolTip"/>
  </interface>
</node>'''

DIGITS = {
    '0': ('111', '101', '101', '101', '111'),
    '1': ('010', '110', '010', '010', '111'),
    '2': ('111', '001', '111', '100', '111'),
    '3': ('111', '001', '111', '001', '111'),
    '4': ('101', '101', '111', '001', '001'),
    '5': ('111', '100', '111', '001', '111'),
    '6': ('111', '100', '111', '101', '111'),
    '7': ('111', '001', '010', '010', '010'),
    '8': ('111', '101', '111', '101', '111'),
    '9': ('111', '101', '111', '001', '111'),
    '+': ('000', '010', '111', '010', '000'),
}


def count_pixmaps(count):
    """Draw a monochrome badge sized for Cutefish's 16px status items."""
    if count <= 0:
        return []
    compact = count > 99
    label = '99+' if compact else str(count)
    columns = (0, 1, 1, 2) if compact else (0, 0, 1, 1, 2, 2)
    gap = 1 if compact else 2
    width = len(label) * (len(columns) + gap) - gap
    x = (16 - width) // 2

    badge = [[False] * 16 for _ in range(16)]
    for y in range(1, 15):
        inset = 2 if len(label) == 1 else 0
        if y in (1, 14):
            inset += 3
        elif y in (2, 13):
            inset += 1
        badge[y][inset:16 - inset] = [True] * (16 - 2 * inset)

    for digit in label:
        for row, pattern in enumerate(DIGITS[digit]):
            for column, source in enumerate(columns):
                if pattern[source] == '1':
                    badge[3 + 2 * row][x + column] = False
                    badge[4 + 2 * row][x + column] = False
        x += len(columns) + gap

    # StatusNotifierItem carries unpremultiplied ARGB in network byte order.
    # Transparent numbers show the bar background after Cutefish tints the fill.
    opaque, transparent = b'\xff\x20\x20\x20', b'\x00\x00\x00\x00'
    pixmaps = []
    for scale in (1, 2):
        rows = [b''.join((opaque if filled else transparent) * scale for filled in row) * scale
                for row in badge]
        pixmaps.append((16 * scale, 16 * scale, b''.join(rows)))
    return pixmaps


def xdg_path(variable, fallback):
    path = Path(os.environ.get(variable, ''))
    return (path if path.is_absolute() else Path.home() / fallback) / 'cutefish-app-center'


def read_record(path):
    try:
        with path.open('rb') as file:
            limit = 1024 * 1024
            raw = file.read(limit + 1)
        record = json.loads(raw) if len(raw) <= limit else None
        if isinstance(record, dict) and record.get('version') == 1:
            return record
    except (OSError, ValueError, RecursionError):
        pass
    return {}


def update_count(interval, report):
    if interval not in ('daily', 'weekly'):
        return 0, False
    result = read_record(report)
    checked, count, complete = (result.get(key) for key in ('checked_at', 'update_count', 'complete'))
    if type(checked) is int and checked > 0 and type(count) is int and count > 0 and type(complete) is bool:
        return count, complete
    return 0, False


def log(message):
    print(f'Cutefish App Center: {message}', file=sys.stderr, flush=True)


def open_updates():
    desktop = Gio.DesktopAppInfo.new(APP_ID + '.desktop')
    if desktop and 'Updates' in desktop.list_actions():
        desktop.launch_action('Updates', None)
    else:
        Gio.Subprocess.new(['cutefish-app-center', '--updates'], Gio.SubprocessFlags.NONE)


def call_bus(connection, method, args, signature):
    return connection.call_sync(
        'org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus',
        method, GLib.Variant(signature, args), None, Gio.DBusCallFlags.NO_AUTO_START, 2000, None,
    ).unpack()[0]


def acquire_name(connection, name):
    # DO_NOT_QUEUE; already owner is also a success.
    return call_bus(connection, 'RequestName', (name, 4), '(su)') in (1, 4)


class UpdateIndicator:
    def __init__(self, connection, activate=open_updates):
        self.connection = connection
        self.activate = activate
        self.count = 0
        self.complete = False
        self.watcher_owner = ''
        self.owns_item = False
        interface = Gio.DBusNodeInfo.new_for_xml(ITEM_XML).interfaces[0]
        self.object_id = connection.register_object(
            ITEM_PATH, interface, self.method_called, self.property, None,
        )
        self.watch_id = Gio.bus_watch_name_on_connection(
            connection, WATCHER, Gio.BusNameWatcherFlags.NONE,
            self.watcher_appeared, self.watcher_vanished,
        )

    def watcher_appeared(self, _connection, _name, owner):
        self.watcher_owner = owner
        self.register_item()

    def watcher_vanished(self, _connection, _name):
        self.watcher_owner = ''

    def register_item(self):
        if self.watcher_owner and self.owns_item:
            self.connection.call(
                self.watcher_owner, '/StatusNotifierWatcher', WATCHER,
                'RegisterStatusNotifierItem', GLib.Variant('(s)', (ITEM_NAME,)), None,
                Gio.DBusCallFlags.NO_AUTO_START, 2000, None, None,
            )

    def update(self, count, complete):
        count_changed = count != self.count
        changed = count_changed or complete != self.complete
        self.count, self.complete = count, complete
        if count == 0:
            if self.owns_item:
                # Releasing the name removes the item even on hosts that ignore Passive.
                call_bus(self.connection, 'ReleaseName', (ITEM_NAME,), '(s)')
                self.owns_item = False
        elif not self.owns_item:
            self.owns_item = acquire_name(self.connection, ITEM_NAME)
            self.register_item()
        elif changed:
            if count_changed:
                self.connection.emit_signal(None, ITEM_PATH, ITEM_INTERFACE, 'NewIcon', None)
            for signal in ('NewTitle', 'NewToolTip'):
                self.connection.emit_signal(None, ITEM_PATH, ITEM_INTERFACE, signal, None)

    def property(self, _connection, _sender, _path, _interface, name):
        if name == 'ItemIsMenu':
            return GLib.Variant('b', False)
        if name == 'IconPixmap':
            return GLib.Variant('a(iiay)', count_pixmaps(self.count))
        noun = 'update' if self.count == 1 else 'updates'
        title = f'{self.count} {noun} available'
        detail = 'Open Cutefish App Center to review updates.'
        if not self.complete:
            title = 'At least ' + title
            detail = 'Some software sources could not be checked.'
        if name == 'ToolTip':
            return GLib.Variant('(sa(iiay)ss)', (ICON, [], title, detail))
        return GLib.Variant('s', {
            'Category': 'SystemServices',
            # A launcher icon resolved from either Id or IconName would hide the badge.
            'Id': ITEM_NAME,
            'Title': title,
            'Status': 'Active',
            'IconName': '',
        }[name])

    def method_called(self, _connection, _sender, _path, _interface, _method, _parameters, invocation):
        invocation.return_value(None)
        try:
            self.activate()
        except GLib.Error as error:
            log(f'could not open Updates: {error.message}')

    def close(self):
        self.update(0, False)
        Gio.bus_unwatch_name(self.watch_id)
        self.connection.unregister_object(self.object_id)


class UpdateMonitor:
    def __init__(self, indicator, preferences, report):
        self.indicator = indicator
        self.preferences = preferences
        self.report = report
        self.interval = None
        self.started = False
        self.worker = None
        self.worker_timeout = None
        self.monitors = []
        for path in (preferences, report):
            try:
                watch = Gio.File.new_for_path(str(path)).monitor_file(Gio.FileMonitorFlags.WATCH_MOVES)
                watch.connect('changed', self.files_changed)
                self.monitors.append(watch)
            except GLib.Error as error:
                log(f'could not watch update status: {error.message}')
        self.refresh()
        GLib.timeout_add_seconds(30, self.first_check)
        GLib.timeout_add_seconds(300, self.tick)

    def refresh(self):
        self.interval = read_record(self.preferences).get('update_check_interval')
        self.indicator.update(*update_count(self.interval, self.report))

    def files_changed(self, _monitor, _file, _other_file, _event):
        previous = self.interval
        self.refresh()
        if self.started and self.interval != previous:
            self.check()

    def first_check(self):
        self.started = True
        self.tick()
        return GLib.SOURCE_REMOVE

    def tick(self):
        self.refresh()
        self.check()
        return GLib.SOURCE_CONTINUE

    def check(self):
        if self.worker is not None or self.interval not in ('daily', 'weekly'):
            return
        backend = Path(__file__).with_name('app_center_backend.py')
        try:
            self.worker = Gio.Subprocess.new(
                ['/usr/bin/python3', str(backend), '--check-updates'], Gio.SubprocessFlags.STDOUT_SILENCE,
            )
            self.worker_timeout = GLib.timeout_add_seconds(300, self.check_timed_out)
            self.worker.wait_check_async(None, self.check_finished)
        except GLib.Error as error:
            log(f'could not start the background check: {error.message}')

    def check_timed_out(self):
        self.worker_timeout = None
        self.worker.force_exit()
        log('the background check timed out.')
        return GLib.SOURCE_REMOVE

    def check_finished(self, worker, result):
        timed_out = self.worker_timeout is None
        if not timed_out:
            GLib.source_remove(self.worker_timeout)
            self.worker_timeout = None
        try:
            worker.wait_check_finish(result)
        except GLib.Error as error:
            if not timed_out:
                log(f'background check failed: {error.message}')
        finally:
            self.worker = None
        self.refresh()


def main():
    try:
        connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        if not acquire_name(connection, APP_ID + '.UpdateMonitor'):
            return 0
        indicator = UpdateIndicator(connection)
        preferences = Path(os.environ.get('CUTEFISH_APP_CENTER_PREFERENCES')
                           or xdg_path('XDG_CONFIG_HOME', '.config') / 'preferences.json')
        report = xdg_path('XDG_DATA_HOME', '.local/share') / 'update-check.json'
        UpdateMonitor(indicator, preferences, report)
        try:
            GLib.MainLoop().run()
        finally:
            indicator.close()
    except GLib.Error as error:
        log(error.message)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
