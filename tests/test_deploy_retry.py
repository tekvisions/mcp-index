import importlib.util
from pathlib import Path
import ssl
import io
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

spec = importlib.util.spec_from_file_location('deployment', Path(__file__).parents[1] / 'deploy.py')
deployment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deployment)

class Response:
    status = 200
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self): return b'ok'

class DeploymentRetryTests(unittest.TestCase):
    def test_content_addressed_upload_retries_transient_reset(self):
        with patch.object(deployment.urllib.request, 'urlopen', side_effect=[URLError(ConnectionResetError('reset')), Response()]) as open_url, patch('time.sleep'):
            self.assertEqual(deployment.req('https://api.vercel.com/v2/files?teamId=fixture', data=b'fixture', method='POST'), (200, b'ok'))
            self.assertEqual(open_url.call_count, 2)

    def test_safe_get_retries_temporary_server_failure(self):
        failure = HTTPError('https://api.vercel.com/v9/projects/fixture', 503, 'unavailable', {}, io.BytesIO(b'failure'))
        with patch.object(deployment.urllib.request, 'urlopen', side_effect=[failure, Response()]) as open_url, patch('time.sleep'):
            self.assertEqual(deployment.req('https://api.vercel.com/v9/projects/fixture'), (200, b'ok'))
            self.assertEqual(open_url.call_count, 2)

    def test_permanent_http_failure_is_not_retried(self):
        failure = HTTPError('https://api.vercel.com/v2/files', 403, 'forbidden', {}, io.BytesIO(b'failure'))
        with patch.object(deployment.urllib.request, 'urlopen', side_effect=failure) as open_url:
            self.assertEqual(deployment.req('https://api.vercel.com/v2/files', data=b'fixture', method='POST')[0], 403)
            self.assertEqual(open_url.call_count, 1)

    def test_uncertain_deployment_creation_is_never_repeated(self):
        with patch.object(deployment.urllib.request, 'urlopen', side_effect=URLError(ConnectionResetError('reset'))) as open_url:
            with self.assertRaises(URLError): deployment.req('https://api.vercel.com/v13/deployments', data=b'{}', method='POST')
            self.assertEqual(open_url.call_count, 1)

    def test_certificate_failure_is_not_retried_or_bypassed(self):
        with patch.object(deployment.urllib.request, 'urlopen', side_effect=URLError(ssl.SSLCertVerificationError('certificate failure'))) as open_url:
            with self.assertRaises(URLError): deployment.req('https://api.vercel.com/v2/files', data=b'fixture', method='POST')
            self.assertEqual(open_url.call_count, 1)

    def test_implicit_post_creation_is_never_repeated(self):
        with patch.object(deployment.urllib.request, 'urlopen', side_effect=URLError(ConnectionResetError('reset'))) as open_url:
            with self.assertRaises(URLError): deployment.req('https://api.vercel.com/v13/deployments', data=b'{}')
            self.assertEqual(open_url.call_count, 1)

    def test_transient_upload_attempts_are_bounded(self):
        with patch.object(deployment.urllib.request, 'urlopen', side_effect=URLError(TimeoutError('timeout'))) as open_url, patch('time.sleep'):
            with self.assertRaises(URLError): deployment.req('https://api.vercel.com/v2/files', data=b'fixture', method='POST')
            self.assertEqual(open_url.call_count, 4)

    def test_upload_rate_limit_respects_retry_after(self):
        failure = HTTPError('https://api.vercel.com/v2/files', 429, 'rate limited', {'Retry-After': '3'}, io.BytesIO(b'failure'))
        with patch.object(deployment.urllib.request, 'urlopen', side_effect=[failure, Response()]), patch('time.sleep') as sleep:
            self.assertEqual(deployment.req('https://api.vercel.com/v2/files', data=b'fixture', method='POST')[0], 200)
            sleep.assert_called_once_with(3)

    def test_rejected_upload_never_creates_a_partial_deployment(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, 'index.html').write_text('fixture')
            with patch.object(deployment, 'ROOT', folder), patch.object(deployment, 'TOKEN', 'fixture'), patch.object(deployment, '_preflight_overwrite_guard'), patch.object(deployment, 'req', return_value=(403, b'failure')) as request:
                self.assertEqual(deployment.main(), 1)
                self.assertEqual(request.call_count, 1)

if __name__ == '__main__': unittest.main()
