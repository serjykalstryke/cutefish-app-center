"""Source trust, scope, stale reviews and exact Snap channel transactions."""
import base64
import contextlib
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, MagicMock, patch

spec=importlib.util.spec_from_file_location('backend',Path(__file__).parents[1]/'backend/app_center_backend.py')
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)

class SourceTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory()
  self.env=patch.dict(os.environ,{'XDG_STATE_HOME':self.temp.name});self.env.start()
 def tearDown(self):self.env.stop();self.temp.cleanup()
 def repo(self,**kw):return dict(dict(id='example',name='Example',url='https://example.org/repo',enabled=True,verified=True,scope='user',installed_count=0),**kw)
 def target(self,**kw):return dict(dict(source='flatpak',id='example',scope='user'),**kw)
 def test_source_identifiers_and_scopes_are_strict(self):
  for target in [self.target(scope='root'),self.target(id='../bad'),dict(source='deb',id='repo',scope='user'),dict(source='snap',id='snap\n')]:
   with self.subTest(target=target),self.assertRaises(b.AppCenterError):b.source_identity(target)
 def test_source_labels_hide_login_credentials_and_url_parameters(self):
  text=b.display_source('Debian https://alice:secret@example.org/repo?token=hidden#other')
  self.assertEqual(text,'Debian https://example.org/repo')
 def test_provider_failure_does_not_hide_other_sources(self):
  with patch.object(b,'debian_sources',side_effect=b.AppCenterError('offline')),patch.object(b.shutil,'which',return_value='/usr/bin/provider'),patch.object(b,'flatpak_sources',side_effect=lambda scope:[self.repo(scope=scope)]),patch.object(b,'snap_api',side_effect=b.AppCenterError('stopped')):
   result=b.software_sources()
  self.assertEqual(len(result['repositories']),2);self.assertEqual(len(result['providers']),4)
  self.assertFalse(result['providers'][0]['available']);self.assertTrue(result['providers'][1]['available'])
 def test_flatpak_removal_is_blocked_for_apps_and_runtimes(self):
  with patch.object(b,'flatpak_sources',return_value=[self.repo(installed_count=1)]):
   with self.assertRaisesRegex(b.AppCenterError,'runtimes'):b.plan_source(self.target(),'remove')
 def test_scope_is_retained_during_review_and_commit(self):
  api=Mock();api.get_remote_by_name.return_value=Mock()
  with patch.object(b,'flatpak_sources',side_effect=[[self.repo()],[self.repo()],[self.repo(enabled=False)]]),patch.object(b,'flatpak_api',return_value=(None,None,api)) as factory:
   b.apply_source(b.plan_source(self.target(),'disable'))
  factory.assert_called_once_with('user');api.get_remote_by_name.assert_called_once_with('example',None)
  api.get_remote_by_name.return_value.set_disabled.assert_called_once_with(True)
 def test_changed_source_review_never_mutates(self):
  api=Mock()
  with patch.object(b,'flatpak_sources',side_effect=[[self.repo()],[self.repo(url='https://other.org/repo')]]),patch.object(b,'flatpak_api',return_value=(None,None,api)):
   approved=b.plan_source(self.target(),'disable')
   with self.assertRaisesRegex(b.AppCenterError,'changed'):b.apply_source(approved)
  api.modify_remote.assert_not_called()
 def test_authorization_denial_reaches_caller(self):
  api=Mock();api.modify_remote.side_effect=b.AppCenterError('authorization denied')
  with patch.object(b,'flatpak_sources',return_value=[self.repo()]),patch.object(b,'flatpak_api',return_value=(None,None,api)):
   with self.assertRaisesRegex(b.AppCenterError,'authorization denied'):b.apply_source(b.plan_source(self.target(),'disable'))
 def test_backend_checks_change_was_applied(self):
  with patch.object(b,'flatpak_sources',return_value=[self.repo()]),patch.object(b,'flatpak_api',return_value=(None,None,Mock())):
   with self.assertRaisesRegex(b.AppCenterError,'did not apply'):b.apply_source(b.plan_source(self.target(),'disable'))
 def test_debian_accepts_only_configured_ids_and_enable_disable(self):
  with patch.object(b,'debian_sources',return_value=[dict(id='known',name='Debian',enabled=True)]):
   for target,action in [(dict(source='deb',id='unknown'),'disable'),(dict(source='deb',id='known'),'add')]:
    with self.assertRaises(b.AppCenterError):b.plan_source(target,action)
 def test_already_requested_state_is_not_applied(self):
  with patch.object(b,'flatpak_sources',return_value=[self.repo()]):
   with self.assertRaisesRegex(b.AppCenterError,'already'):b.plan_source(self.target(),'enable')
 def read_repository(self,data):
  opener=MagicMock();opener.open.return_value.__enter__.return_value.read.return_value=data
  with patch.object(b,'public_https',side_effect=lambda url,**kw: str(url).startswith('https://example.org/')),patch.object(b.urllib.request,'build_opener',return_value=opener):
   return b.read_flatpak_repository('https://example.org/repo.flatpakrepo')
 def test_unsigned_private_and_oversized_repo_files_are_refused(self):
  good=b'[Flatpak Repo]\nUrl=https://example.org/repo\nGPGKey='+base64.b64encode(b'signing key')+b'\n'
  self.assertEqual(self.read_repository(good)[0],good)
  for data in [good.replace(b'GPGKey=',b'NoKey='),good.replace(b'https://example.org/repo',b'http://localhost/repo'),good.replace(base64.b64encode(b'signing key'),b'%%%'),b'x'*(256*1024+1)]:
   with self.subTest(data=data[:50]),self.assertRaises(b.AppCenterError):self.read_repository(data)
 def test_repository_redirects_reject_private_destinations(self):
  with self.assertRaises(b.AppCenterError):b.RepositoryRedirect().redirect_request(None,None,302,'',{},'http://127.0.0.1/key')
 def test_changed_repository_file_requires_new_review(self):
  F,GLib,api=Mock(),Mock(),Mock();F.Remote.new_from_file.return_value.get_gpg_verify.return_value=True
  F.Remote.new_from_file.return_value.get_url.return_value='https://example.org/repo'
  with patch.object(b,'flatpak_sources',return_value=[]),patch.object(b,'read_flatpak_repository',side_effect=[(b'first','a'*64),(b'changed','b'*64)]),patch.object(b,'flatpak_api',return_value=(F,GLib,api)):
   approved=b.plan_source(self.target(repository_url='https://example.org/repo.flatpakrepo'),'add')
   with self.assertRaisesRegex(b.AppCenterError,'changed'):b.apply_source(approved)
  api.add_remote.assert_not_called()
 def test_signature_verification_is_explicitly_enabled_for_added_sources(self):
  F=Mock();F.Remote.new_from_file.return_value.get_url.return_value='https://example.org/repo'
  with patch.object(b,'flatpak_sources',return_value=[]),patch.object(b,'read_flatpak_repository',return_value=(b'repo','a'*64)),patch.object(b,'flatpak_api',return_value=(F,Mock(),Mock())):
   b.plan_source(self.target(repository_url='https://example.org/repo.flatpakrepo'),'add')
  F.Remote.new_from_file.return_value.set_gpg_verify.assert_called_once_with(True)

class ChannelTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,{'XDG_STATE_HOME':self.temp.name});self.env.start()
  self.channels={c:dict(revision=r,version=r,confinement='strict') for c,r in [('latest/stable','10'),('latest/beta','20'),('esr/stable','8')]}
  self.installed=dict(name='example',revision='10',version='1',channel='latest/candidate',**{'tracking-channel':'latest/stable'})
  self.calls=[]
 def tearDown(self):self.env.stop();self.temp.cleanup()
 def api(self,path,body=None):
  if body:
   self.calls.append(body);self.installed.update(revision=body.get('revision','10'));self.installed['tracking-channel']=body.get('channel','latest/stable')
   return dict(type='sync')
  if path.startswith('/v2/find'):return dict(result=[dict(name='example',channels=self.channels)])
  return dict(result=self.installed.copy())
 def target(self,**kw):return dict(dict(source='snap',id='example',name='Example',requested_channel='latest/beta'),**kw)
 def test_track_channel_and_branch_validation(self):
  self.assertEqual(b.snap_channel('stable'),'latest/stable');self.assertEqual(b.snap_channel('esr/beta/test'),'esr/beta/test')
  for value in ['unknown','latest/invalid','../stable','latest/stable/../bad','latest/stable\n',None]:
   with self.subTest(value=value),self.assertRaises(b.AppCenterError):b.snap_channel(value)
 def test_install_uses_exact_reviewed_channel_and_revision(self):
  with patch.object(b,'snap_api',side_effect=self.api):
   approved=b.plan(self.target(),'install');self.assertIn('testing builds',approved['note']);b.apply(approved)
  self.assertEqual(self.calls,[dict(action='install',channel='latest/beta',revision='20')])
 def test_switch_uses_tracking_channel_and_keeps_future_refresh_policy(self):
  with patch.object(b,'snap_api',side_effect=self.api):
   approved=b.plan(self.target(),'switch-channel');self.assertEqual(approved['target']['previous_channel'],'latest/stable');b.apply(approved)
  self.assertEqual(self.calls,[dict(action='refresh',channel='latest/beta',revision='20')]);self.assertEqual(self.installed['tracking-channel'],'latest/beta')
 def test_removed_channel_or_new_revision_requires_fresh_review(self):
  for changed in ['revision','removed','installed']:
   with self.subTest(changed=changed),patch.object(b,'snap_api',side_effect=self.api):
    self.setUpState();approved=b.plan(self.target(),'switch-channel')
    if changed=='revision':self.channels['latest/beta']['revision']='21'
    elif changed=='removed':self.channels.pop('latest/beta')
    else:self.installed['revision']='11'
    with self.assertRaises(b.AppCenterError):b.apply(approved)
    self.assertEqual(self.calls,[])
 def setUpState(self):
  self.channels['latest/beta']=dict(revision='20',version='20',confinement='strict');self.installed['revision']='10';self.calls=[]
 def test_developer_confinement_and_unknown_channels_are_refused(self):
  with patch.object(b,'snap_api',side_effect=self.api):
   with self.assertRaises(b.AppCenterError):b.plan(self.target(requested_channel='latest/edge'),'install')
   self.channels['latest/beta']['confinement']='devmode'
   with self.assertRaisesRegex(b.AppCenterError,'Developer'):b.plan(self.target(),'install')
 def test_completed_transaction_must_reach_reviewed_channel(self):
  def api(path,body=None):
   if body:return dict(type='sync')
   return self.api(path)
  with patch.object(b,'snap_api',side_effect=api):
   with self.assertRaisesRegex(b.AppCenterError,'without reaching'):b.apply(b.plan(self.target(),'switch-channel'))
 def test_details_use_installed_tracking_and_offer_real_channels(self):
  with patch.object(b,'snap_api',side_effect=self.api),patch.object(b,'launch_spec',return_value=None):
   item=b.app_details(dict(source='snap',id='example'),artwork=False)['item']
  self.assertEqual(item['requested_channel'],'latest/stable');self.assertEqual(item['tracking_channel'],'latest/stable')
  self.assertEqual(len(item['channel_options']),3);self.assertFalse(item['channel_change'])

if __name__=='__main__':unittest.main()
