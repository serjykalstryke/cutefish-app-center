"""Run with dbus-run-session and the PackageKit client library installed."""
import importlib.util
import os
from pathlib import Path
import subprocess
import unittest

os.environ['DBUS_SYSTEM_BUS_ADDRESS']=os.environ['DBUS_SESSION_BUS_ADDRESS']
spec=importlib.util.spec_from_file_location('backend',Path(__file__).parents[1]/'backend/app_center_backend.py')
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
 def test_bulk_update_preserves_ids_architectures_and_restart_signals(self):
  ids=['fixture;2.0;amd64;repo','other;3.0;arm64;repo']
  pk=b.PackageKit()
  changes,_=pk.transaction('UpdatePackages','(tas)',(6,ids))
  self.assertEqual([c['id'] for c in changes],ids)
  self.assertTrue(all(c['info']=='updating' for c in changes))
  events=[]
  _,restarts=pk.transaction('UpdatePackages','(tas)',(2,ids),report=lambda text,pct,phase:events.append((phase,pct)))
  self.assertEqual(restarts,[2])
  self.assertEqual(events,[('authorization',None),('downloading',45),('applying',None)])
 def test_repository_read_toggle_and_verification_over_real_dbus(self):
  rows=b.debian_sources();self.assertEqual(rows,[dict(id='fixture-repo:exact-id',name='A Debian repository',enabled=True)])
  approved=b.plan_source(dict(source='deb',id=rows[0]['id']),'disable');b.apply_source(approved)
  self.assertFalse(b.debian_sources()[0]['enabled'])
  with self.assertRaisesRegex(b.AppCenterError,'already'):b.apply_source(approved)
  b.apply_source(b.plan_source(dict(source='deb',id=rows[0]['id']),'enable'))
  self.assertTrue(b.debian_sources()[0]['enabled'])
 def test_errors_reach_the_caller(self):
  with self.assertRaisesRegex(b.AppCenterError,'Fixture error'):b.PackageKit().transaction('GetUpdates','(t)',(0,))

if __name__=='__main__':unittest.main()
