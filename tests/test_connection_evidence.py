import unittest,tempfile,pathlib
import build_data
class ConnectionEvidenceTests(unittest.TestCase):
 def test_missing_endpoint_does_not_become_a_copyable_placeholder(self):
  self.assertIsNone(build_data.install_snippet({'name':'ac.inference.sh/mcp','transport':'Remote','registries':['hosted']})[2])
 def test_website_is_not_assumed_to_be_an_endpoint(self):
  self.assertIsNone(build_data.install_snippet({'transport':'Remote','website':'https://example.com/pricing'})[2])
 def test_missing_package_identifier_is_not_guessed(self):
  for reg in ['npm','pypi','oci','nuget']:
   with self.subTest(reg=reg):self.assertIsNone(build_data.install_snippet({'name':'io.github.example/tool','registries':[reg]})[2])
 def test_only_publisher_declared_https_remote_is_copyable(self):
  self.assertEqual(build_data.install_snippet({'transport':'Remote','remotes':[{'type':'streamable-http','url':'https://example.com/mcp'}]})[2],'https://example.com/mcp')
  for url in ['javascript:alert(1)','https://user:password@example.com/mcp','https://example.com/{tenant}','https://<server-endpoint>']:
   with self.subTest(url=url):self.assertIsNone(build_data.install_snippet({'transport':'Remote','remotes':[{'url':url}]})[2])
 def test_package_metacharacters_cannot_become_commands(self):
  for package in ['x; touch /tmp/pwn','$(echo hi)','--help','x\nwhoami']:
   self.assertIsNone(build_data.install_snippet({'registries':['npm'],'pkg_ids':{'npm':package}})[2])
 def test_real_scoped_package_is_preserved(self):
  self.assertIn('@scope/server',build_data.install_snippet({'registries':['npm'],'pkg_ids':{'npm':'@scope/server'}})[2])
if __name__=='__main__':unittest.main()
