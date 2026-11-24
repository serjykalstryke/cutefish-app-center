import importlib.util
import json
from pathlib import Path
import tempfile
import time
import unittest

from gi.repository import Gio, GLib


spec = importlib.util.spec_from_file_location(
    'update_indicator', Path(__file__).parents[1] / 'backend/update_indicator.py',
)
indicator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(indicator)


class UpdateIndicatorTests(unittest.TestCase):
    def test_only_opted_in_valid_update_reports_are_shown(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / 'update-check.json'
            report.write_text(json.dumps(dict(version=1, update_count=4, complete=False, checked_at=84)))
            self.assertEqual(indicator.update_count('off', report), (0, False))
            self.assertEqual(indicator.update_count('weekly', report), (4, False))
            report.write_text(json.dumps(dict(version=1, update_count=True, complete=True, checked_at=84)))
            self.assertEqual(indicator.update_count('weekly', report), (0, False))

    def test_numeric_badge_is_monochrome_argb_at_standard_tray_sizes(self):
        self.assertEqual(indicator.count_pixmaps(0), [])
        first = indicator.count_pixmaps(7)
        second = indicator.count_pixmaps(18)
        self.assertNotEqual(first, second)
        self.assertEqual(indicator.count_pixmaps(100), indicator.count_pixmaps(888))
        self.assertNotEqual(indicator.count_pixmaps(100), indicator.count_pixmaps(99))
        self.assertEqual([(w, h) for w, h, _ in second], [(16, 16), (32, 32)])
        for width, height, data in second:
            self.assertEqual(len(data), width * height * 4)
            self.assertEqual(set(data[::4]), {0, 255})
            opaque_colors = {data[i + 1:i + 4] for i in range(0, len(data), 4) if data[i]}
            self.assertEqual(opaque_colors, {b'\x20\x20\x20'})

    def test_reconnect_hide_and_open_updates(self):
        callbacks = []
        registrations = []
        bus = Gio.TestDBus.new(Gio.TestDBusFlags.NONE)
        bus.up()
        self.addCleanup(bus.down)
        address = bus.get_bus_address()
        flags = (Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT |
                 Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION)

        def connect():
            connection = Gio.DBusConnection.new_for_address_sync(address, flags, None, None)
            self.addCleanup(connection.close_sync, None)
            return connection

        def received(_connection, _sender, _path, _interface, _method, parameters, invocation):
            registrations.append(parameters.unpack()[0])
            invocation.return_value(None)

        def make_host():
            host = connect()
            xml = f'''<node><interface name="{indicator.WATCHER}">
              <method name="RegisterStatusNotifierItem"><arg type="s" direction="in"/></method>
            </interface></node>'''
            host.register_object(
                '/StatusNotifierWatcher', Gio.DBusNodeInfo.new_for_xml(xml).interfaces[0],
                received, None, None,
            )
            self.assertTrue(indicator.acquire_name(host, indicator.WATCHER))
            return host

        item = indicator.UpdateIndicator(connect(), lambda: callbacks.append('opened'))
        self.addCleanup(item.close)
        host = make_host()
        item.update(3, False)
        self.wait_for(lambda: registrations == [indicator.ITEM_NAME])

        # Verify the host gets the actual status item payload via GetAll.
        def properties():
            values = []

            def read_properties(connection, result):
                values.extend(connection.call_finish(result).unpack())

            host.call(
                indicator.ITEM_NAME, indicator.ITEM_PATH, 'org.freedesktop.DBus.Properties',
                'GetAll', GLib.Variant('(s)', (indicator.ITEM_INTERFACE,)), None,
                Gio.DBusCallFlags.NONE, 2000, None, read_properties,
            )
            self.wait_for(lambda: bool(values))
            return values[0]

        initial = properties()
        self.assertEqual(initial['Title'], 'At least 3 updates available')
        self.assertEqual(initial['IconName'], '')
        self.assertNotEqual(initial['Id'], indicator.APP_ID)
        self.assertEqual([(w, h, bytes(data)) for w, h, data in initial['IconPixmap']],
                         indicator.count_pixmaps(3))

        icon_changes = []
        host.signal_subscribe(
            None, indicator.ITEM_INTERFACE, 'NewIcon', indicator.ITEM_PATH, None,
            Gio.DBusSignalFlags.NONE, lambda *_: icon_changes.append(True),
        )
        item.update(143, True)
        self.wait_for(lambda: icon_changes)
        updated = properties()
        self.assertEqual(updated['ToolTip'][2], '143 updates available')
        self.assertEqual([(w, h, bytes(data)) for w, h, data in updated['IconPixmap']],
                         indicator.count_pixmaps(143))
        self.assertNotEqual(initial['IconPixmap'], updated['IconPixmap'])

        # Registration is repeated when the compositor is replaced.
        indicator.call_bus(host, 'ReleaseName', (indicator.WATCHER,), '(s)')
        host = make_host()
        self.wait_for(lambda: registrations == [indicator.ITEM_NAME, indicator.ITEM_NAME])
        host.call(
            indicator.ITEM_NAME, indicator.ITEM_PATH, indicator.ITEM_INTERFACE,
            'Activate', GLib.Variant('(ii)', (0, 0)), None,
            Gio.DBusCallFlags.NONE, 2000, None, None,
        )
        self.wait_for(lambda: callbacks == ['opened'])
        item.update(0, False)
        self.assertFalse(indicator.call_bus(host, 'NameHasOwner', (indicator.ITEM_NAME,), '(s)'))

    def wait_for(self, predicate):
        deadline = time.monotonic() + 3
        context = GLib.MainContext.default()
        while not predicate() and time.monotonic() < deadline:
            while context.pending():
                context.iteration(False)
            time.sleep(.005)
        self.assertTrue(predicate())


if __name__ == '__main__':
    unittest.main()
