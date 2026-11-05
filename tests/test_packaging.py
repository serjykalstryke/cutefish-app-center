"""Real ELF fixtures catch missing and accidentally static runtime linkage."""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT=Path(__file__).parents[1]/'scripts/package.py'

@unittest.skipUnless(shutil.which('g++') and shutil.which('readelf') and shutil.which('ldd'), 'requires system C++ build tools')
class PackagingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name)
        cls.source=cls.root/'main.cpp'
        cls.source.write_text('#include <iostream>\nint main(){std::cout << "fixture" << std::endl;}\n')
        cls.build(cls.source,'shared')
        cls.build(cls.source,'static','-static-libstdc++')
        library=cls.root/'helper.cpp';library.write_text('extern "C" void missing(); extern "C" void helper(){missing();}\n')
        subprocess.run(['g++','-fPIC','-shared',str(library),'-Wl,-soname,libfixture.so','-o',str(cls.root/'libfixture.so')],check=True,capture_output=True)
        caller=cls.root/'caller.cpp';caller.write_text('#include <iostream>\nextern "C" void helper();int main(){std::cout << "fixture";helper();}\n')
        cls.build(caller,'unresolved','-L'+str(cls.root),'-lfixture','-Wl,-rpath,$ORIGIN','-Wl,--allow-shlib-undefined')
        cls.build(caller,'missing-lib','-L'+str(cls.root),'-lfixture','-Wl,-rpath,$ORIGIN/missing','-Wl,--allow-shlib-undefined')
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    @classmethod
    def build(cls,source,name,*flags):
        subprocess.run(['g++',str(source),'-o',str(cls.root/name),*flags],check=True,capture_output=True)
    def check(self,name):
        return subprocess.run([sys.executable,str(SCRIPT),str(self.root/name),'--check-only'],capture_output=True,text=True)
    def test_shared_runtime_passes_without_writing_package(self):
        result=self.check('shared');self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('Runtime dependencies verified',result.stdout)
        self.assertEqual(list(self.root.glob('*.deb')),[])
    def test_static_runtime_is_rejected(self):
        result=self.check('static');self.assertNotEqual(result.returncode,0)
        self.assertIn('link directly to shared libstdc++',result.stderr)
    def test_missing_runtime_library_is_rejected(self):
        result=self.check('missing-lib');self.assertNotEqual(result.returncode,0)
        self.assertIn('not found',result.stderr)
    def test_unresolved_shared_library_symbol_is_rejected(self):
        result=self.check('unresolved');self.assertNotEqual(result.returncode,0)
        self.assertIn('undefined symbol:',result.stderr)

if __name__=='__main__':unittest.main()
