"""Exercise transport interruption recovery using real loopback HTTP requests."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
import sys
import threading
import tempfile
import json
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from dev.tools.remote.model_gateway import Gateway, apply_profile, PROFILES


class ModelGatewayTests(unittest.TestCase):
    def exercise(self, status=200, disconnect_first=True, profile=None):
        requests = []
        class Upstream(BaseHTTPRequestHandler):
            def do_POST(self):
                requests.append(self.rfile.read(int(self.headers['Content-Length'])))
                if disconnect_first and len(requests) == 1:
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                    return
                body = b'{"model":"test","choices":[]}'
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *args):
                pass
        upstream = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
        temporary = tempfile.TemporaryDirectory()
        gateway = Gateway(('127.0.0.1', 0), upstream.server_address, recovery_s=1, retry_s=.01,
                          profile=profile, audit_dir=temporary.name if profile else None)
        threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in (upstream, gateway)]
        for thread in threads:
            thread.start()
        payload = b'{"temperature":0,"max_tokens":8192,"messages":[]}'
        try:
            request = urllib.request.Request(
                f'http://127.0.0.1:{gateway.server_port}/v1/chat/completions',
                data=payload, headers={'Content-Type':'application/json'})
            try:
                with urllib.request.urlopen(request, timeout=3) as response:
                    actual_status, body = response.status, response.read()
            except urllib.error.HTTPError as response:
                actual_status, body = response.code, response.read()
            self.assertEqual(actual_status, status)
            self.assertEqual(body, b'{"model":"test","choices":[]}')
            self.assertEqual(requests, [apply_profile(payload, profile)] * (2 if disconnect_first else 1))
            if profile:
                audits = list(Path(temporary.name).glob('*.request.json'))
                self.assertEqual(len(audits), 1)
                audit = json.loads(audits[0].read_text())
                self.assertEqual(audit['original'], json.loads(payload))
                self.assertEqual(audit['effective'], json.loads(requests[0]))
                responses = list(Path(temporary.name).glob('*.response.json'))
                self.assertEqual(json.loads(responses[0].read_text())['raw_text'], body.decode())
        finally:
            for server in (gateway, upstream):
                server.shutdown()
                server.server_close()
            for thread in threads:
                thread.join()
            temporary.cleanup()

    def test_interrupted_post_retries_identical_bytes(self):
        self.exercise()

    def test_upstream_http_error_is_forwarded_without_retry(self):
        self.exercise(status=503, disconnect_first=False)

    def test_diagnostic_profile_and_retry_are_audited(self):
        self.exercise(profile='think-off-greedy')

    def test_sampling_profile_applies_to_any_caller(self):
        self.exercise(disconnect_first=False, profile='think-on-sampled')

    def test_thinking_pair_differs_only_in_switch(self):
        payload = b'{"model":"fixed","max_tokens":8192,"messages":[{"role":"user","content":"unchanged"}],"temperature":0,"top_p":1}'
        on = json.loads(apply_profile(payload, 'think-on-greedy'))
        off = json.loads(apply_profile(payload, 'think-off-greedy'))
        self.assertTrue(on.pop('chat_template_kwargs')['enable_thinking'])
        self.assertFalse(off.pop('chat_template_kwargs')['enable_thinking'])
        self.assertEqual(on, off)
        self.assertEqual(on['messages'], json.loads(payload)['messages'])
        self.assertEqual(on['max_tokens'], 8192)

    def test_profile_requires_audit(self):
        with self.assertRaises(ValueError):
            Gateway(('127.0.0.1', 0), ('127.0.0.1', 1), profile='think-on-greedy')

    def test_profile_rejects_changed_budget(self):
        with self.assertRaises(ValueError):
            apply_profile(b'{"messages":[],"max_tokens":100}', 'think-on-greedy')

    def test_recovery_has_a_deadline(self):
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0))
            unreachable = reservation.getsockname()
        gateway = Gateway(('127.0.0.1', 0), unreachable, recovery_s=.06, retry_s=.02)
        thread = threading.Thread(target=gateway.serve_forever, daemon=True)
        thread.start()
        try:
            request = urllib.request.Request(f'http://127.0.0.1:{gateway.server_port}/v1/chat/completions',
                                             data=b'{}')
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(request, timeout=2)
            self.assertEqual(caught.exception.code, 502)
        finally:
            gateway.shutdown()
            gateway.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()
