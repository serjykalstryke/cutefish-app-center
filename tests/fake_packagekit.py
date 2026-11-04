"""Protocol fixture for a private dbus-run-session bus; never changes software."""
from gi.repository import Gio, GLib
import os
ROOT='/org/freedesktop/PackageKit'
NAME='org.freedesktop.PackageKit'
IFACE=NAME+'.Transaction'
XML='''<node><interface name="org.freedesktop.PackageKit">
<method name="CreateTransaction"><arg type="o" direction="out"/></method></interface></node>'''
TX='''<node><interface name="org.freedesktop.PackageKit.Transaction">
<method name="SetHints"><arg type="as" direction="in"/></method>
<method name="Resolve"><arg type="t" direction="in"/><arg type="as" direction="in"/></method>
<method name="GetUpdates"><arg type="t" direction="in"/></method>
<method name="InstallPackages"><arg type="t" direction="in"/><arg type="as" direction="in"/></method>
<method name="RemovePackages"><arg type="t" direction="in"/><arg type="as" direction="in"/><arg type="b" direction="in"/><arg type="b" direction="in"/></method>
<method name="InstallFiles"><arg type="t" direction="in"/><arg type="as" direction="in"/></method>
<signal name="Package"><arg type="u"/><arg type="s"/><arg type="s"/></signal>
<signal name="ErrorCode"><arg type="u"/><arg type="s"/></signal>
<signal name="Finished"><arg type="u"/><arg type="u"/></signal>
</interface></node>'''
bus=Gio.bus_get_sync(Gio.BusType.SESSION,None)
count=0
loop=GLib.MainLoop()
def method(conn,sender,path,iface,method,args,invocation):
 global count
 if method=='CreateTransaction':
  count+=1;path=ROOT+'/t'+str(count)
  bus.register_object(path,Gio.DBusNodeInfo.new_for_xml(TX).interfaces[0],globals()['method'],None,None)
  invocation.return_value(GLib.Variant('(o)',(path,)))
 elif method=='SetHints':invocation.return_value(None)
 else:
  invocation.return_value(None)
  def result():
   if method=='Resolve':
    name=args.unpack()[1][0]
    bus.emit_signal(sender,path,IFACE,'Package',GLib.Variant('(uss)',(2,name+';1.0;amd64;fixture','A protocol fixture')))
   elif method=='GetUpdates':
    bus.emit_signal(sender,path,IFACE,'ErrorCode',GLib.Variant('(us)',(1,'Fixture error')))
   else:
    flags=args.unpack()[0]
    if flags & 4:
     bus.emit_signal(sender,path,IFACE,'Package',GLib.Variant('(uss)',(28 if method=='RemovePackages' else 27,'fixture;1.0;amd64;fixture','A simulated change')))
   bus.emit_signal(sender,path,IFACE,'Finished',GLib.Variant('(uu)',(2 if method=='GetUpdates' else 1,0)))
   return False
  GLib.timeout_add(5,result)
bus.register_object(ROOT,Gio.DBusNodeInfo.new_for_xml(XML).interfaces[0],method,None,None)
bus.call_sync('org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','RequestName',GLib.Variant('(su)',(NAME,0)),None,0,3000,None)
print('ready',flush=True)
loop.run()
