"""Loopback HTTP gateway with bounded transport recovery for both experiment modes.

Only transport failures are retried, with the exact same request bytes. Retrying
an interrupted POST may duplicate remote inference; each attempt is logged here.
Retries preserve the exact upstream bytes. Optional diagnostic profiles change
only declared generation settings, equally for both callers, and require audit.
"""
from __future__ import annotations

import argparse
from http.client import HTTPConnection, HTTPException
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import time
import uuid
import hashlib
from pathlib import Path


# Development experiments only; never silently enable this for normal runs.
PROFILES = {
    'think-on-greedy': {'chat_template_kwargs': {'enable_thinking': True},
                        'temperature': 0.0, 'top_p': 1.0, 'seed': 20261013},
    'think-off-greedy': {'chat_template_kwargs': {'enable_thinking': False},
                         'temperature': 0.0, 'top_p': 1.0, 'seed': 20261013},
    'think-on-sampled': {'chat_template_kwargs': {'enable_thinking': True},
                         'temperature': 0.6, 'top_p': 0.95, 'top_k': 20,
                         'min_p': 0.0, 'seed': 20261013},
}


def apply_profile(body, profile):
    """Leave messages, model, token cap and all other request fields intact."""
    if profile is None:
        return body
    payload = json.loads(body)
    if not isinstance(payload, dict) or not isinstance(payload.get('messages'), list):
        raise ValueError('diagnostic requests require a messages list')
    if payload.get('max_tokens') != 8192 or payload.get('stream', False):
        raise ValueError('diagnostic requires max_tokens=8192 and non-streaming')
    template = dict(payload.get('chat_template_kwargs') or {})
    settings = PROFILES[profile]
    template.update(settings['chat_template_kwargs'])
    payload.update({k: v for k, v in settings.items() if k != 'chat_template_kwargs'})
    payload['chat_template_kwargs'] = template
    return json.dumps(payload, ensure_ascii=False).encode()


HOP_HEADERS = {'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
               'te', 'trailer', 'transfer-encoding', 'upgrade', 'host', 'content-length'}


class Gateway(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, upstream, *, recovery_s=270, retry_s=3,
                 profile=None, audit_dir=None):
        if profile is not None and (profile not in PROFILES or audit_dir is None):
            raise ValueError('a known diagnostic profile requires an audit directory')
        self.profile = profile
        self.audit_dir = Path(audit_dir) if audit_dir is not None else None
        if self.audit_dir is not None:
            self.audit_dir.mkdir(parents=True, exist_ok=True)
        self.upstream, self.recovery_s, self.retry_s = upstream, recovery_s, retry_s
        super().__init__(address, Handler)

    def audit(self, request_id, kind, value):
        if self.audit_dir is not None:
            # Each HTTP request has a unique ID; no authorization headers stored.
            with (self.audit_dir / f'{request_id}.{kind}.json').open('x') as output:
                json.dump(value, output, ensure_ascii=False, indent=2)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.forward()

    def do_POST(self):
        self.forward()

    def forward(self):
        started = time.monotonic()
        deadline = started + (self.server.recovery_s if self.command == 'POST' else 8)
        request_id, attempt = uuid.uuid4().hex[:12], 0
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP_HEADERS}
        diagnostic = self.command == 'POST' and self.path == '/v1/chat/completions'
        if diagnostic and self.server.profile is not None:
            try:
                original = body
                body = apply_profile(body, self.server.profile)
                self.server.audit(request_id, 'request', {
                    'profile': self.server.profile, 'started_at': time.time(),
                    'original_sha256': hashlib.sha256(original).hexdigest(),
                    'effective_sha256': hashlib.sha256(body).hexdigest(),
                    'original': json.loads(original), 'effective': json.loads(body)})
            except (ValueError, TypeError, OSError):
                self.send_error(400, 'invalid diagnostic request or unavailable audit')
                return
        while True:
            attempt += 1
            connection = HTTPConnection(*self.server.upstream,
                                        timeout=max(.01, deadline - time.monotonic()))
            try:
                connection.request(self.command, self.path, body=body, headers=headers)
                response = connection.getresponse()
                data = response.read()
                status = response.status
                response_headers = [(k, v) for k, v in response.getheaders()
                                    if k.lower() not in HOP_HEADERS]
            except (OSError, HTTPException) as exc:
                remaining = deadline - time.monotonic()
                print(json.dumps(dict(event='transport_retry', request_id=request_id,
                                      attempt=attempt, error_type=type(exc).__name__,
                                      remaining_s=round(max(0, remaining), 2))), flush=True)
                if remaining <= 0:
                    status, response_headers = 502, [('Content-Type', 'application/json')]
                    data = json.dumps({'error':{'type':'transport_unavailable',
                        'message':'SSH/model transport recovery deadline exceeded'}}).encode()
                    break
                time.sleep(min(self.server.retry_s, remaining))
                continue
            finally:
                connection.close()
            break
        print(json.dumps(dict(event='response', request_id=request_id, attempt=attempt,
                              method=self.command, path=self.path, status=status,
                              elapsed_s=round(time.monotonic()-started, 3))), flush=True)
        if diagnostic and self.server.profile is not None:
            try:
                self.server.audit(request_id, 'response', {
                    'status': status, 'attempts': attempt,
                    'elapsed_s': time.monotonic() - started,
                    'raw_text': data.decode('utf-8', errors='replace')})
            except OSError:
                self.send_error(500, 'diagnostic response audit failed')
                return
        try:
            self.send_response(status)
            for key, value in response_headers:
                self.send_header(key, value)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--upstream-port', type=int, required=True)
    parser.add_argument('--recovery-s', type=float, default=270)
    parser.add_argument('--profile', choices=sorted(PROFILES))
    parser.add_argument('--audit-dir', type=Path)
    args = parser.parse_args()
    if args.recovery_s <= 0 or args.port == args.upstream_port:
        parser.error('require positive recovery time and different ports')
    if args.profile is not None and args.audit_dir is None:
        parser.error('--profile requires --audit-dir')
    with Gateway(('127.0.0.1', args.port), ('127.0.0.1', args.upstream_port),
                 recovery_s=args.recovery_s, profile=args.profile,
                 audit_dir=args.audit_dir) as server:
        server.serve_forever()


if __name__ == '__main__':
    main()
