"""Installed-app classification and whole-system update transaction contracts."""
import contextlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

spec=importlib.util.spec_from_file_location('backend',Path(__file__).parents[1]/'backend/app_center_backend.py')
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)

def deb(name='demo',**fields):return dict(dict(source='deb',id=name,name=name,scope='system',architecture='amd64',version='1',installed=True,protected=False,summary='Package',icon='application-x-deb'),**fields)
def group(source='deb',**fields):return dict(dict(source=source,scope='system',name=source,targets=['demo;2;amd64;repo'],changes=[dict(info='updating',id='demo;2;amd64;repo')]),**fields)
def plan(groups):
 p=dict(groups=groups);p['fingerprint']=b.update_plan_fingerprint(p);return p

class ManagementTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
  env=patch.dict(os.environ,XDG_DATA_HOME=str(self.root/'data'),XDG_CACHE_HOME=str(self.root/'cache'));env.start();self.addCleanup(env.stop)
 def test_appstream_and_visible_launchers_identify_apps_without_name_blacklist(self):
  installed=[deb('libdrawing'),deb('opaque-name'),deb('libcodec'),deb('headless-service')]
  metadata={'libdrawing':dict(desktop_app=True,name='Drawing')}
  desktops={'opaque-name':dict(desktop_app=True,name='Writer',icon='writer',is_application=True)}
  with patch.object(b,'dpkg_installed',return_value=installed),patch.object(b,'appstream',return_value=metadata),patch.object(b,'debian_desktop_packages',return_value=desktops):items=b.management_provider('deb')
  self.assertEqual({i['id'] for i in items if i['is_application']},{'libdrawing','opaque-name'})
  self.assertTrue(all(i['installed_version']=='1' for i in items))
 def test_hidden_and_nodisplay_launchers_are_not_application_evidence(self):
  visible=self.root/'visible.desktop';hidden=self.root/'hidden.desktop'
  visible.write_text('[Desktop Entry]\nType=Application\nName=Useful App\nExec=/does/not/run\nIcon=useful\n')
  hidden.write_text('[Desktop Entry]\nType=Application\nName=Helper\nExec=/does/not/run\nNoDisplay=true\n')
  self.assertEqual(b.desktop_record(str(visible))['name'],'Useful App');self.assertIsNone(b.desktop_record(str(hidden)))
 def test_package_ownership_does_not_follow_nonapplication_paths(self):
  output='libwriter: /usr/share/applications/writer.desktop\nlibcodec: /usr/share/applications/../codec.desktop\ndiversion by foo: /etc/other.desktop\n'
  with patch.object(b,'run',return_value=output),patch.object(b,'desktop_record',return_value=dict(name='Writer')) as desktop:
   result=b.debian_desktop_packages()
  self.assertEqual(set(result),{'libwriter'});desktop.assert_called_once_with('/usr/share/applications/writer.desktop')
 def test_multiarch_and_flatpak_installations_remain_distinct(self):
  self.assertEqual(b.software_key(deb('demo')),b.software_key(deb('demo:amd64')))
  self.assertNotEqual(b.software_key(deb('demo')),b.software_key(deb('demo:arm64',architecture='arm64')))
  f=dict(source='flatpak',id='org.example.App',scope='user',arch='x86_64',branch='stable',remote='flathub')
  keys={b.software_key(dict(f,**change)) for change in ({},{'scope':'system'},{'branch':'beta'},{'ref_kind':'runtime'},{'remote':'other'})}
  self.assertEqual(len(keys),5)
 def test_flatpak_runtime_is_explicit_and_never_launchable(self):
  f=dict(source='flatpak',id='org.example.Platform',scope='system',arch='x86_64',branch='stable',remote='flathub',ref_kind='runtime')
  self.assertEqual(b.flatpak_ref(f),'runtime/org.example.Platform/x86_64/stable')
  with patch.object(b,'flatpak_installed',side_effect=AssertionError('runtime considered launchable')):self.assertIsNone(b.launch_spec(f))
 def test_shared_runtime_remove_is_refused(self):
  f=dict(source='flatpak',id='org.example.Platform',scope='system',arch='x86_64',branch='stable',remote='flathub',ref_kind='runtime')
  with self.assertRaisesRegex(b.AppCenterError,'removal'):b.plan(f,'remove')
 def test_snap_system_component_removal_is_refused(self):
  with patch.object(b,'snap_api',return_value=dict(result=dict(type='base',confinement='strict'))):
   with self.assertRaisesRegex(b.AppCenterError,'protected Snap'):b.plan(dict(source='snap',id='core24'),'remove')
 def test_provider_failure_keeps_installed_inventory_available(self):
  item=dict(deb(),install_key='demo',is_application=True)
  def provider(source,*args):
   if source=='snap':raise b.AppCenterError('offline')
   return [item] if source=='deb' else []
  with patch.object(b,'management_sources',return_value=['deb','snap']),patch.object(b,'management_provider',side_effect=provider):result=b.management_inventory()
  self.assertEqual(result['items'],[item]);self.assertFalse(result['complete']);self.assertIn('snap: offline',result['warnings'])
 def test_full_inventory_is_not_cut_off_at_search_display_limits(self):
  items=[dict(deb(str(n)),install_key=str(n),is_application=False) for n in range(501)]
  with patch.object(b,'management_sources',return_value=['deb']),patch.object(b,'management_provider',side_effect=lambda s,*a:items if s=='deb' else []):result=b.management_inventory()
  self.assertEqual(len(result['items']),501)
 def test_snap_bases_are_hidden_but_exported_instance_apps_are_kept(self):
  path=self.root/'demo_instance_app.desktop';path.write_text('[Desktop Entry]\nType=Application\nName=Demo\nExec=/unused\nX-SnapInstanceName=demo_instance\n')
  items=[dict(source='snap',id=i,name=i,scope='system',snap_type=t,icon='application-x-executable') for i,t in [('core24','base'),('daemon','app'),('demo_instance','app')]]
  with patch.object(b,'snap_items',return_value=items),patch.object(b.Path,'glob',return_value=[path]):result=b.management_provider('snap')
  self.assertEqual([i['id'] for i in result if i['is_application']],['demo_instance'])
 def test_protected_updates_are_allowed_but_protected_removals_are_not(self):
  item=dict(deb('libc6',protected=True),package_id='libc6;2;amd64;repo')
  pk=Mock();pk.transaction.return_value=([dict(info='updating',id=item['package_id'])],[])
  with patch.object(b,'PackageKit',return_value=pk),patch.object(b,'dpkg_installed',return_value=[item]):self.assertIsNotNone(b.debian_update_group([item]))
  pk.transaction.return_value=([dict(info='removing',id='libc6;1;amd64;installed')],[])
  with patch.object(b,'PackageKit',return_value=pk),patch.object(b,'dpkg_installed',return_value=[item]):
   with self.assertRaisesRegex(b.AppCenterError,'protected'):b.debian_update_group([item])
 def test_held_packages_are_not_submitted_to_update_transaction(self):
  pk=Mock();pk.transaction.return_value=([],[])
  items=[dict(deb('held'),package_id='held;2;amd64;repo',update_blocked=True),dict(deb(),package_id='demo;2;amd64;repo')]
  with patch.object(b,'PackageKit',return_value=pk):result=b.debian_update_group(items)
  self.assertEqual(result['targets'],['demo;2;amd64;repo'])
  pk.transaction.assert_called_once_with('UpdatePackages','(tas)',(6,['demo;2;amd64;repo']))
 def test_incomplete_source_check_blocks_update_all_before_modification(self):
  with patch.object(b,'management_inventory',return_value=dict(complete=False,warnings=['snap: offline'])),patch.object(b,'debian_update_group') as update:
   with self.assertRaisesRegex(b.AppCenterError,'No updates have been applied'):b.prepare_all_updates()
  update.assert_not_called()
 def test_update_all_includes_system_packages_runtimes_and_snap_bases(self):
  items=[dict(deb('libc6'),package_id='libc6;2;amd64;repo'),dict(source='flatpak',id='org.example.Platform',scope='system',ref_kind='runtime',arch='x86_64',branch='stable',remote='flathub',update_commit='a'*64),dict(source='snap',id='core24',name='core24',revision='2',installed_revision='1')]
  with patch.object(b,'management_inventory',return_value=dict(complete=True,items=items)),patch.object(b,'debian_update_group',return_value=group()),patch.object(b,'flatpak_update_group',return_value=group('flatpak',targets=[dict(ref='runtime/org.example.Platform/x86_64/stable',commit='a'*64)])) as fp:
   result=b.prepare_all_updates()
  self.assertEqual([g['source'] for g in result['groups']],['deb','flatpak','snap'])
  self.assertEqual(fp.call_args.args[1][0]['ref'],'runtime/org.example.Platform/x86_64/stable')
  self.assertIn('regardless of the current list filters',result['note'])
 def test_restart_messages_distinguish_applications_from_system_restarts(self):
  self.assertEqual(b.restart_notice(['none']),(False,''))
  flag,text=b.restart_notice(['application']);self.assertFalse(flag);self.assertIn('applications',text)
  flag,text=b.restart_notice(['system']);self.assertTrue(flag);self.assertIn('system restart',text)
 def test_individual_flatpak_update_uses_source_commit_and_dependency_review(self):
  target=dict(source='flatpak',id='org.example.App',scope='user',arch='x86_64',branch='stable',remote='flathub',update_commit='b'*64)
  candidate=dict(target,update_commit='a'*64)
  g=group('flatpak',scope='user',targets=[dict(ref='app/org.example.App/x86_64/stable',commit='a'*64)],changes=[dict(info='update',id='app/org.example.App/x86_64/stable',remote='flathub',commit='a'*64)],note='Full dependencies')
  with patch.object(b,'management_flatpaks',return_value=[candidate]) as inventory,patch.object(b,'flatpak_update_group',return_value=g) as review:
   approved=b.plan(target,'update')
  inventory.assert_called_once_with(updates=True,scopes=('user',))
  self.assertEqual(review.call_args.args[1][0]['commit'],'a'*64);self.assertEqual(approved['changes'],g['changes'])
 def test_individual_flatpak_apply_uses_reviewed_transaction(self):
  target=dict(source='flatpak',id='org.example.App',scope='user',arch='x86_64',branch='stable',remote='flathub')
  g=group('flatpak',scope='user',targets=[dict(ref='app/org.example.App/x86_64/stable',commit='a'*64)])
  approved=dict(target=target,action='update',fingerprint='a'*64,flatpak_group=g)
  with patch.object(b,'plan',return_value=approved),patch.object(b,'flatpak_update_group') as apply,patch.object(b,'stream_command') as cli:
   b.apply(approved)
  apply.assert_called_once_with('user',g['targets'],approved=g);cli.assert_not_called()
 def test_stale_plan_is_rejected_before_any_modification(self):
  approved=plan([group()]);current=plan([group(targets=['other;3;amd64;repo'])])
  with patch.object(b,'prepare_all_updates',return_value=current),patch.object(b,'PackageKit') as pk:
   with self.assertRaisesRegex(b.AppCenterError,'nothing has been applied'):b.apply_all_updates(approved)
  pk.assert_not_called()
 def test_debian_apply_preserves_exact_architectures_and_restart_result(self):
  g=group(targets=['demo;2;arm64;repo'],changes=[dict(info='updating',id='demo;2;arm64;repo')]);approved=plan([g])
  pk=Mock();pk.transaction.side_effect=[(g['changes'],[]),([],['system'])]
  with patch.object(b,'prepare_all_updates',return_value=approved),patch.object(b,'PackageKit',return_value=pk):result=b.apply_all_updates(approved)
  self.assertEqual(pk.transaction.call_args_list[-1].args,('UpdatePackages','(tas)',(2,['demo;2;arm64;repo'])))
  self.assertTrue(result['restart']);self.assertEqual(result['errors'],[])
 def test_partial_failure_stops_later_sources_and_reports_completed_changes(self):
  groups=[group(),group('flatpak',targets=[]),group('snap',targets=[dict(name='demo',revision='2')])];approved=plan(groups)
  pk=Mock();pk.transaction.side_effect=[(groups[0]['changes'],[]),([],[])]
  with patch.object(b,'prepare_all_updates',return_value=approved),patch.object(b,'PackageKit',return_value=pk),patch.object(b,'flatpak_update_group',side_effect=b.AppCenterError('authorization denied')),patch.object(b,'snap_api') as snap:
   result=b.apply_all_updates(approved)
  self.assertEqual(result['completed'],['deb']);self.assertEqual(result['pending'],['snap']);self.assertIn('authorization denied',result['message']);snap.assert_not_called()
 def test_changed_debian_dependencies_block_real_transaction(self):
  approved=plan([group()]);pk=Mock();pk.transaction.return_value=([dict(info='installing',id='extra;1;amd64;repo')],[])
  with patch.object(b,'prepare_all_updates',return_value=approved),patch.object(b,'PackageKit',return_value=pk):result=b.apply_all_updates(approved)
  self.assertEqual(pk.transaction.call_count,1);self.assertTrue(result['errors']);self.assertEqual(result['completed'],[])
 def test_snap_refresh_is_restricted_to_reviewed_names(self):
  item=dict(source='snap',id='core24',name='Core',revision='2',installed_revision='1',version='2')
  g=b.snap_update_group([item]);approved=plan([g])
  with patch.object(b,'prepare_all_updates',return_value=approved),patch.object(b,'management_provider',return_value=[item]),patch.object(b,'snap_api',return_value=dict(type='async',change='12')) as api,patch.object(b,'wait_snap_update') as wait:
   result=b.apply_all_updates(approved)
  api.assert_called_once_with('/v2/snaps',dict(action='refresh',snaps=['core24']));self.assertFalse(result['errors']);wait.assert_called_once()
 def test_caller_groups_do_not_override_recomputed_plan(self):
  current=plan([group()]);approved=dict(current,groups=[group(targets=['untrusted;999;amd64;other'])]);pk=Mock();pk.transaction.side_effect=[(current['groups'][0]['changes'],[]),([],[])]
  with patch.object(b,'prepare_all_updates',return_value=current),patch.object(b,'PackageKit',return_value=pk):b.apply_all_updates(approved)
  self.assertEqual(pk.transaction.call_args.args[-1],(2,['demo;2;amd64;repo']))

class FakeError(Exception):pass
class FakeOperation:
 def __init__(self,ref,commit='a'*64,kind=1):self.ref,self.commit,self.kind=ref,commit,kind
 def get_ref(self):return self.ref
 def get_commit(self):return self.commit
 def get_operation_type(self):return self.kind
 def get_remote(self):return 'flathub'
 def get_download_size(self):return 1234
class FakeTransaction:
 def __init__(self,operations):self.operations=operations;self.signals={};self.targets=[];self.executed=False
 def set_no_interaction(self,value):self.noninteractive=value
 def add_default_dependency_sources(self):pass
 def connect(self,name,callback):self.signals[name]=callback
 def add_update(self,ref,subpaths,commit):self.targets.append((ref,commit))
 def get_operations(self):return self.operations
 def run(self,_):
  for name in ('ready-pre-auth','ready'):
   if not self.signals[name](self):raise FakeError('aborted before execution')
  self.executed=True

class FlatpakReviewTests(unittest.TestCase):
 def api(self,tx):return (types.SimpleNamespace(Transaction=types.SimpleNamespace(new_for_installation=lambda *_:tx)),types.SimpleNamespace(Error=FakeError),object())
 def test_review_aborts_before_authorization_or_installation(self):
  ref='runtime/org.example.Platform/x86_64/stable';tx=FakeTransaction([FakeOperation(ref)])
  with patch.object(b,'flatpak_api',return_value=self.api(tx)):g=b.flatpak_update_group('system',[dict(ref=ref,commit='a'*64)])
  self.assertFalse(tx.executed);self.assertTrue(tx.noninteractive);self.assertEqual(g['targets'],[dict(ref=ref,commit='a'*64)])
  self.assertFalse(tx.signals['add-new-remote']())
 def test_related_runtime_install_keeps_root_even_if_root_commit_is_current(self):
  root='runtime/org.example.Platform/x86_64/stable';tx=FakeTransaction([FakeOperation('runtime/org.example.Driver/x86_64/stable',kind=0)])
  with patch.object(b,'flatpak_api',return_value=self.api(tx)):g=b.flatpak_update_group('system',[dict(ref=root,commit='b'*64)])
  self.assertEqual(g['targets'],[dict(ref=root,commit='b'*64)]);self.assertEqual(g['changes'][0]['info'],'install');self.assertFalse(tx.executed)
 def test_changed_flatpak_commit_aborts_apply_before_deployment(self):
  ref='app/org.example.App/x86_64/stable';tx=FakeTransaction([FakeOperation(ref,commit='b'*64)])
  approved=dict(changes=[dict(info='update',id=ref,remote='flathub',commit='a'*64)])
  with patch.object(b,'flatpak_api',return_value=self.api(tx)):
   with self.assertRaisesRegex(b.AppCenterError,'dependencies changed'):b.flatpak_update_group('user',[dict(ref=ref,commit='a'*64)],approved)
  self.assertFalse(tx.executed)
 def test_matching_flatpak_plan_is_checked_before_and_after_auth(self):
  ref='app/org.example.App/x86_64/stable';tx=FakeTransaction([FakeOperation(ref)])
  approved=dict(changes=[dict(info='update',id=ref,remote='flathub',commit='a'*64)])
  with patch.object(b,'flatpak_api',return_value=self.api(tx)):b.flatpak_update_group('user',[dict(ref=ref,commit='a'*64)],approved)
  self.assertTrue(tx.executed);self.assertFalse(tx.noninteractive)

if __name__=='__main__':unittest.main()
