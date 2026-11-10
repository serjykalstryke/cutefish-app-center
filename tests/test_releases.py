"""Catalog exclusivity and a disposable filesystem for Debian source switches."""
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch

ROOT=Path(__file__).parents[1]
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
b=load('backend',ROOT/'backend/app_center_backend.py')
d=load('debian_releases',ROOT/'backend/debian_releases.py')

class CatalogTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'preferences.json'
  self.remote_patch=patch.object(b,"flatpak_remote_catalog_releases",return_value={});self.remote_patch.start()
  self.env=patch.dict(os.environ,{'CUTEFISH_APP_CENTER_PREFERENCES':str(self.path),'XDG_CACHE_HOME':self.temp.name});self.env.start()
 def tearDown(self):self.remote_patch.stop();self.env.stop();self.temp.cleanup()
 def preferences(self,**values):self.path.write_text(json.dumps(dict(version=1,catalog_releases=values)))
 def test_missing_invalid_and_unknown_preferences_default_to_stable(self):
  for data in ['broken',json.dumps(dict(version=2,catalog_releases=dict(snap='beta'))),json.dumps(dict(version=1,catalog_releases=['beta'])),json.dumps(dict(version=1,catalog_releases=dict(snap='edge',unknown='beta')))]:
   self.path.write_text(data);self.assertEqual(b.catalog_releases(),{})
 def test_only_selected_flatpak_release_survives_before_application_grouping(self):
  records=[dict(source='flatpak',id='org.example.App',name='Example',scope=scope,remote='flathub'+suffix,branch=branch,arch='x86_64') for scope in ('user','system') for suffix,branch in [('','stable'),('-beta','beta')]]
  for release in ('stable','beta'):
   self.preferences(flatpak=release)
   with patch.object(b,'inventory_provider',return_value=records):result=b.listing(dict(mode='search',source='flatpak',query='example'))
   self.assertEqual(result['total'],1);self.assertEqual(len(result['items']),2)
   self.assertTrue(all(i['branch']==release for i in result['items']))
 def test_flatpak_numeric_stable_branches_and_custom_testing_remotes(self):
  self.assertEqual(b.flatpak_catalog_release(dict(remote='custom',branch='2.40')),'stable')
  for remote,branch in [('flathub-beta','2.40'),('custom','nightly'),('custom-testing','main')]:self.assertEqual(b.flatpak_catalog_release(dict(remote=remote,branch=branch)),'beta')
 def test_one_remote_can_publish_stable_and_beta_branches_without_mixing_results(self):
  records=[dict(source='flatpak',id='org.example.App',name='Example',scope='system',remote='publisher',branch=branch) for branch in ('stable','beta')]
  with patch.object(b,'inventory_provider',return_value=records),patch.object(b,'flatpak_remote_catalog_releases',return_value={'publisher':'stable'}):
   for release in ('stable','beta'):
    self.preferences(flatpak=release);items=b.search_provider('flatpak','example')['items'];self.assertEqual([i['branch'] for i in items],[release])
 def test_custom_named_beta_remote_follows_its_advertised_release(self):
  records=[dict(source='flatpak',id='org.example.App',name='Example',scope='system',remote='preview',branch='2.40')]
  self.preferences(flatpak='stable')
  with patch.object(b,'inventory_provider',return_value=records),patch.object(b,'flatpak_remote_catalog_releases',return_value={'preview':'beta'}):
   self.assertEqual(b.search_provider('flatpak','example')['items'],[])
   self.preferences(flatpak='beta');self.assertEqual(len(b.search_provider('flatpak','example')['items']),1)
 def test_only_official_flathub_addresses_are_collapsed_as_one_family(self):
  for url in ['https://dl.flathub.org/repo/','https://flathub.org/beta-repo/']:self.assertEqual(b.flatpak_catalog_family(dict(url=url)),'flathub')
  self.assertEqual(b.flatpak_catalog_family(dict(url='https://elsewhere.example/repo/')),'')
 def snap(self,ident='example',**kw):return dict(dict(source='snap',id=ident,name=ident.title(),scope='system',channel='stable',version='1'),**kw)
 def test_stable_snap_catalog_preserves_published_tracks(self):
  with patch.object(b,'inventory_provider',return_value=[self.snap(channel='2/stable')]):result=b.search_provider('snap','example')
  self.assertEqual(result['items'][0]['requested_channel'],'2/stable')
 def test_beta_snap_search_never_falls_back_to_stable_and_binds_beta_revision(self):
  self.preferences(snap='beta');records=[self.snap(),self.snap('stable-only')]
  channels=lambda name:[dict(channel='latest/beta' if name=='example' else 'latest/stable',revision='22',version='2b',confinement='strict')]
  with patch.object(b,'inventory_provider',return_value=records),patch.object(b,'cached_snap_channels',side_effect=channels):result=b.search_provider('snap','example')
  self.assertEqual(len(result['items']),1);self.assertEqual(result['items'][0]['requested_channel'],'latest/beta');self.assertEqual(result['items'][0]['revision'],'22')
 def test_snap_beta_channel_failures_remain_visible_without_stable_fallback(self):
  self.preferences(snap='beta')
  def inventory(source,*args):return [self.snap()] if source=='snap' else [dict(source='deb',id='example',name='Example',summary='Example app')]
  with patch.object(b,'inventory_provider',side_effect=inventory),patch.object(b,'cached_snap_channels',side_effect=b.AppCenterError('too many requests')):
   result=b.listing(dict(mode='search',source='all',query='example'))
  self.assertFalse(any(i['source']=='snap' for i in result['items']));self.assertIn('snap: too many requests',result['warnings'])
 def test_beta_snap_requests_wide_search_without_changing_installed_tracking(self):
  self.preferences(snap='beta');calls=[]
  def api(path):
   calls.append(path)
   return dict(result=[dict(name='example',channel='latest/beta',revision='2')]) if path=='/v2/snaps' else dict(result=[dict(name='example',channel='stable',revision='1')])
  with patch.object(b,'snap_api',side_effect=api):
   search=b.snap_items('example');installed=b.snap_items()
  self.assertIn('scope=wide',calls[0]);self.assertEqual(search[0]['channel'],'stable');self.assertEqual(installed[0]['channel'],'latest/beta')
 def test_managed_debian_entries_use_release_review_instead_of_individual_toggles(self):
  ident='/etc/apt/sources.list.d/cutefish-app-center-debian.sources:deb:https:testing:main'
  with patch.object(b,'debian_sources',return_value=[dict(id=ident,name='Debian',enabled=True)]),patch.object(b,'debian_release_system') as factory:
   factory.return_value.status.return_value={'managed_files':['/etc/apt/sources.list.d/cutefish-app-center-debian.sources']}
   with self.assertRaisesRegex(b.AppCenterError,'controlled'):b.plan_source(dict(source='deb',id=ident),'disable')
 def test_catalog_preferences_do_not_filter_installed_or_update_targets(self):
  self.preferences(flatpak='beta',snap='beta')
  records=[dict(source='flatpak',id='org.example.App',name='Example',scope='system',branch=branch,remote='flathub',arch='x86_64') for branch in ('stable','beta')]
  for mode in ('installed','updates'):
   with patch.object(b,'inventory_provider',return_value=records):result=b.listing(dict(mode=mode,source='flatpak'))
   self.assertEqual(len(result['items']),2)
 def test_snap_channel_cache_is_bounded_and_install_reviews_do_not_use_it(self):
  response=dict(result=[dict(name='example',channels={'latest/beta':dict(revision='2',version='2',confinement='strict')})])
  with patch.object(b,'snap_api',return_value=response) as api:
   self.assertEqual(b.cached_snap_channels('example'),b.cached_snap_channels('example'));api.assert_called_once()
  with patch.object(b,'snap_api',side_effect=b.AppCenterError('offline')):
   with self.assertRaises(b.AppCenterError):b.plan(self.snap(requested_channel='latest/beta'),'install')
 def test_beta_search_lookup_limit_is_reported(self):
  self.preferences(snap='beta')
  with patch.object(b,'inventory_provider',return_value=[self.snap('app-'+str(i)) for i in range(40)]),patch.object(b,'cached_snap_channels',return_value=[]) as channels:result=b.search_provider('snap','app')
  self.assertEqual(channels.call_count,24);self.assertIn('best 24',result['warnings'][0])

class HelperPolicyTests(unittest.TestCase):
 def test_policy_requires_active_administrator_authorization_for_one_fixed_script(self):
  policy=ET.parse(ROOT/'data/org.cutefish.AppCenter.policy').getroot();actions=policy.findall('action');self.assertEqual(len(actions),1)
  action=actions[0];self.assertEqual(action.attrib['id'],'org.cutefish.app-center.manage-debian-sources')
  self.assertEqual(action.findtext('defaults/allow_active'),'auth_admin');self.assertEqual(action.findtext('defaults/allow_inactive'),'no');self.assertEqual(action.findtext('defaults/allow_any'),'no')
  self.assertEqual(action.find('annotate').text,'/usr/libexec/cutefish-app-center/debian_sources_helper.py')
 def test_helper_rejects_arguments_before_any_source_commit(self):
  result=subprocess.run(['/usr/bin/python3',str(ROOT/'backend/debian_sources_helper.py'),'--root','/tmp'],input='{}',capture_output=True,text=True)
  self.assertNotEqual(result.returncode,0);self.assertFalse(json.loads(result.stdout)['ok'])


class DebianReleaseTests(unittest.TestCase):
 def setUp(self):
  self.umask=os.umask(0o022)
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.system=d.System(self.root)
  for name in ('/etc/apt/sources.list.d','/usr/share/keyrings'):self.system.path(name).mkdir(parents=True)
  self.system.path('/etc/debian_version').write_text('13.0\n');self.system.path(d.KEYRING).write_bytes(b'fixture archive keyring')
  self.source=self.system.path('/etc/apt/sources.list.d/debian.sources')
  self.original=b'# Keep this comment\nTypes: deb deb-src\nURIs: https://deb.debian.org/debian\nSuites: trixie trixie-updates\nComponents: main contrib non-free-firmware\nSigned-By: /usr/share/keyrings/debian-archive-keyring.gpg\n\nTypes: deb\nURIs: https://security.debian.org/debian-security\nSuites: trixie-security\nComponents: main contrib non-free-firmware\nSigned-By: /usr/share/keyrings/debian-archive-keyring.gpg\n'
  self.source.write_bytes(self.original)
  self.third=self.system.path('/etc/apt/sources.list.d/vendor.list');self.third.write_text('deb [signed-by=/vendor/key] https://vendor.example/repo stable main\n')
 def tearDown(self):self.temp.cleanup();os.umask(self.umask)
 def apply(self,release):return self.system.apply(self.system.plan(release))
 def test_review_is_read_only_and_shows_exact_generated_sources(self):
  plan=self.system.plan('testing');self.assertEqual(self.source.read_bytes(),self.original);self.assertFalse(self.system.path(d.STATE).exists())
  self.assertIn('Suites: testing\n',plan['configuration']);self.assertIn('testing-security',plan['configuration']);self.assertNotIn('testing-updates',plan['configuration'])
  self.assertIn('does not install or downgrade',plan['note']);self.assertIn(d.KEYRING,plan['configuration'])
 def test_switch_testing_unstable_stable_then_restore_exact_originals(self):
  third=self.third.read_bytes()
  for release in ('testing','unstable','stable'):
   self.apply(release);self.assertEqual(self.system.status()['current'],release)
   data=self.system.path(d.MANAGED).read_text();self.assertIn('Suites: '+release,data)
   if release=='unstable':self.assertNotIn('debian-security',data)
   self.assertEqual(self.third.read_bytes(),third)
  self.apply('system');self.assertEqual(self.source.read_bytes(),self.original);self.assertFalse(self.system.path(d.MANAGED).exists());self.assertFalse(self.system.path(d.STATE).exists())
 def test_legacy_entries_are_preserved_in_backups_and_other_repositories_unchanged(self):
  self.source.unlink();legacy=self.system.path('/etc/apt/sources.list');raw=b'# sources\ndeb [arch=amd64 signed-by=/usr/share/keyrings/debian-archive-keyring.gpg] http://deb.debian.org/debian trixie main\ndeb https://vendor.example/debian beta main\n';legacy.write_bytes(raw)
  self.apply('testing');self.assertIn(b'deb https://vendor.example/debian beta main',legacy.read_bytes());self.assertIn(b'# Disabled by Cutefish App Center:',legacy.read_bytes())
  self.apply('system');self.assertEqual(legacy.read_bytes(),raw)
 def test_architecture_types_components_and_existing_backports_are_retained(self):
  self.source.write_bytes(self.original.replace(b'Suites: trixie trixie-updates',b'Suites: trixie trixie-backports').replace(b'Types: deb',b'Architectures: amd64\nTypes: deb'))
  plan=self.system.plan('stable');self.assertIn('stable-backports',plan['configuration']);self.assertIn('Architectures: amd64',plan['configuration']);self.assertIn('Types: deb deb-src',plan['configuration'])
 def test_disabled_sources_are_left_disabled_and_mixed_stanzas_are_not_rewritten(self):
  disabled=b'\n\nTypes: deb\nURIs: https://deb.debian.org/debian\nSuites: unstable\nComponents: main\nEnabled: no\n';self.source.write_bytes(self.original+disabled)
  self.apply('testing');self.assertTrue(self.source.read_bytes().endswith(disabled));self.apply('system')
  self.source.write_bytes(self.original.replace(b'URIs: https://deb.debian.org/debian\n',b'URIs: https://deb.debian.org/debian https://elsewhere.example/repo\n'))
  with self.assertRaisesRegex(d.ReleaseError,'mixes'):self.system.plan('testing')
 def test_stale_reviews_and_invalid_release_never_write(self):
  plan=self.system.plan('testing');self.source.write_bytes(self.original+b'\n# external edit\n')
  with self.assertRaisesRegex(d.ReleaseError,'changed'):self.system.apply(plan)
  self.assertFalse(self.system.path(d.STATE).exists())
  for value in ('../etc/passwd','forky;command',None):
   with self.assertRaises(d.ReleaseError):self.system.plan(value)
 def test_external_edits_and_additional_debian_sources_are_not_overwritten(self):
  self.apply('testing');self.source.write_bytes(self.source.read_bytes()+b'\n# administrator edit\n')
  with self.assertRaisesRegex(d.ReleaseError,'outside'):self.system.plan('system')
  self.source.write_bytes(self.source.read_bytes().replace(b'\n# administrator edit\n',b''))
  extra=self.system.path('/etc/apt/sources.list.d/extra.list');extra.write_text('deb https://deb.debian.org/debian stable main\n')
  with self.assertRaisesRegex(d.ReleaseError,'Additional'):self.system.plan('stable')
 def test_writable_files_symlinks_and_insecure_source_options_are_refused(self):
  for raw in [self.original.replace(b'Types: deb deb-src',b'Trusted: yes\nTypes: deb deb-src'),self.original.replace(d.KEYRING.encode(),b'/tmp/untrusted.gpg')]:
   self.source.write_bytes(raw)
   with self.assertRaises(d.ReleaseError):self.system.plan('testing')
  self.source.write_bytes(self.original);self.source.chmod(0o666)
  with self.assertRaises(d.ReleaseError):self.system.plan('testing')
  self.source.chmod(0o644);self.source.unlink();self.source.symlink_to(self.third)
  with self.assertRaises(d.ReleaseError):self.system.plan('testing')
 def test_failure_rolls_back_and_never_claims_completion(self):
  real=d.atomic;failed=False
  def write(path,data,mode=0o644):
   nonlocal failed
   if path==self.system.path(d.MANAGED) and not failed:failed=True;raise OSError('disk write failure')
   return real(path,data,mode)
  with patch.object(d,'atomic',side_effect=write):
   with self.assertRaisesRegex(d.ReleaseError,'restored'):self.apply('testing')
  self.assertEqual(self.source.read_bytes(),self.original);self.assertFalse(self.system.path(d.STATE).exists())
 def test_interrupted_switch_can_restore_original_sources(self):
  real=d.atomic
  def write(path,data,mode=0o644):
   if path==self.system.path(d.MANAGED):raise SystemExit('simulated power loss')
   return real(path,data,mode)
  with patch.object(d,'atomic',side_effect=write):
   with self.assertRaises(SystemExit):self.apply('testing')
  self.assertTrue(self.system.status()['recovery']);self.apply('system');self.assertEqual(self.source.read_bytes(),self.original)
 def test_unprivileged_restore_review_uses_the_same_identity_as_helper(self):
  self.apply('testing')
  with patch.object(d.os,'access',return_value=False):plan=self.system.plan('system')
  self.assertEqual(plan['fingerprint'],self.system.plan('system')['fingerprint']);self.system.apply(plan)
 def test_backups_are_private_and_tampered_backups_are_refused(self):
  self.apply('testing');state=self.system.state();backup=self.system.path('/var/lib/cutefish-app-center/source-backups')/state['originals'][0]['original']
  self.assertEqual(stat.S_IMODE(backup.stat().st_mode),0o600);backup.write_text('tampered')
  with self.assertRaisesRegex(d.ReleaseError,'backup'):self.system.plan('system')
 def test_existing_unmanaged_destination_and_unrecognized_sources_are_refused(self):
  self.system.path(d.MANAGED).write_text('administrator file')
  with self.assertRaisesRegex(d.ReleaseError,'unmanaged'):self.system.plan('testing')
  self.system.path(d.MANAGED).unlink();self.source.write_bytes(self.original.replace(b'https://deb.debian.org',b'https://custom-mirror.example').replace(b'https://security.debian.org',b'https://other.example'))
  self.assertFalse(self.system.status()['available'])
 def test_official_keyring_symlink_is_allowed_only_inside_system_keyrings(self):
  key=self.system.path(d.KEYRING);key.rename(key.with_suffix('.pgp'));key.symlink_to(key.with_suffix('.pgp').name)
  self.assertTrue(self.system.status()['available']);key.unlink();key.symlink_to(self.third)
  with self.assertRaisesRegex(d.ReleaseError,'keyring'):self.system.plan('testing')
 def test_mirror_file_and_source_permissions_must_be_preserved(self):
  mirrors=self.system.path('/etc/apt/mirrors');mirrors.mkdir();(mirrors/'debian.list').write_text('https://deb.debian.org/debian\n')
  self.source.write_bytes(self.original.replace(b'https://deb.debian.org/debian\n',b'mirror+file:/etc/apt/mirrors/debian.list/\n'))
  self.apply('testing');self.source.chmod(0o600)
  with self.assertRaisesRegex(d.ReleaseError,'permissions'):self.system.plan('stable')

if __name__=='__main__':unittest.main()
