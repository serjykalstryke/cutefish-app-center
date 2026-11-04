"""Run with dbus-run-session and the PackageKit client library installed."""
import importlib.util
import os
from pathlib import Path
import subprocess
import unittest

os.environ['DBUS_SYSTEM_BUS_ADDRESS']=os.environ['DBUS_SESSION_BUS_ADDRESS']
spec=importlib.util.spec_from_file_location('backend',Path(__file__).parents[1]/'backend/store_backend.py')
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
class ProtocolTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.server=subprocess.Popen(['/usr/bin/python3',str(Path(__file__).with_name('fake_packagekit.py'))],stdout=subprocess.PIPE,text=True)
  assert cls.server.stdout.readline().strip()=='ready'
 @classmethod
 def tearDownClass(cls):
  cls.server.terminate();cls.server.wait();cls.server.stdout.close()
 def test_resolve_and_simulation_over_real_dbus(self):
  pk=b.PackageKit()
  self.assertEqual(pk.resolve('fixture'),'fixture;1.0;amd64;fixture')
  changes,_=pk.transaction('InstallPackages','(tas)',(6,['fixture;1.0;amd64;fixture']))
  self.assertEqual(changes[0]['info'],'install')
  changes,_=pk.transaction('RemovePackages','(tasbb)',(6,['fixture;1.0;amd64;fixture'],True,False))
  self.assertEqual(changes[0]['info'],'remove')
 def test_errors_reach_the_caller(self):
  with self.assertRaisesRegex(b.StoreError,'Fixture error'):b.PackageKit().transaction('GetUpdates','(t)',(0,))

if __name__=='__main__':unittest.main()
