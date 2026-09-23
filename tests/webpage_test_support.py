"""Loopback hydration fixture shared by native and opt-in host regressions."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import time
from uuid import uuid4


@contextmanager
def delayed_webpage(transport="fetch"):
    sentinel = "Hydration evidence " + uuid4().hex

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            if transport == "redirect" and self.path == "/fixture.html":
                self.send_response(302)
                self.send_header("Location", "/fixture.html?second")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if self.path == "/delayed":
                if transport in ("stream", "tampered-stream", "slow-stream"):
                    body = ("stream prefix " + sentinel).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    try:
                        self.wfile.write(b"stream prefix "); self.wfile.flush()
                        time.sleep(6.3 if transport == "slow-stream" else 2.3)
                        self.wfile.write(sentinel.encode()); self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                    return
                time.sleep(2.3)
                body = sentinel.encode()
                content_type = "text/plain; charset=utf-8"
            else:
                # The sentinel is absent from HTML/JS; only the delayed response has it.
                body = b'''<!doctype html><html><head><title>Quasi hydration fixture</title>
<meta property="og:site_name" content="Quasi Fixture"></head><body><main>
<h1>Quasi hydration fixture</h1><p>Immediate evidence about preserving delayed page content.</p>
<script>window.addEventListener('load', () => {
fetch('/delayed').then(r => r.text()).then(text => {
const p = document.createElement('p'); p.textContent = text;
document.querySelector('main').appendChild(p);
});});</script></main></body></html>'''
                if transport == "fragment":
                    body = body.replace(b"fetch('/delayed').then", b"setTimeout(() => { location.hash = 'hydrating'; document.querySelector('main').dataset.fragmentObserved = location.hash; }, 300); fetch('/delayed').then")
                if transport == "same-url-reload":
                    body = body.replace(b"fetch('/delayed').then", b"if (!sessionStorage.reloaded) { sessionStorage.reloaded = 'yes'; setTimeout(() => location.reload(), 100); } fetch('/delayed').then")
                if transport == "javascript":
                    body = body.replace(b"fetch('/delayed').then", b"setTimeout(() => { location.href = 'javascript:void(0)'; }, 300); fetch('/delayed').then")
                if transport == "reload" and "?second" not in self.path:
                    body = b"<html><body>first<script>fetch('/delayed'); setTimeout(() => location.replace('/fixture.html?second'), 100)</script></body></html>"
                if transport == "xhr":
                    body = body.replace(b"fetch('/delayed').then(r => r.text()).then(text => {", b"const xhr = new XMLHttpRequest(); xhr.open('GET', '/delayed'); xhr.onload = () => { const text = xhr.responseText;")
                    body = body.replace(b"});});</script>", b"}; xhr.send(); });</script>")
                if transport == "tampered-stream":
                    body = body.replace(b"<script>", b"""<script>
const nativeThen = Promise.prototype.then;
const nativeText = Response.prototype.text;
window.fetch = () => Promise.resolve(new Response('fake'));
XMLHttpRequest.prototype.send = () => {};
JSON.stringify = () => 'fake'; Math.imul = () => 0;
Array.from = () => []; String.prototype.charCodeAt = () => 0;
performance.getEntriesByType = () => [];
Response.prototype.clone = () => { throw Error('patched clone'); };
Response.prototype.text = () => { throw Error('patched text'); };
Promise.prototype.then = () => { throw Error('patched then'); };
ReadableStreamDefaultReader.prototype.read = () => { throw Error('patched reader'); };
EventTarget.prototype.addEventListener = () => { throw Error('patched listener'); };
EventTarget.prototype.removeEventListener = () => { throw Error('patched listener'); };
</script><script>""")
                    # Keep page hydration functional while sabotaging tracker intrinsics.
                    body = body.replace(b"window.addEventListener('load', () => {", b"setTimeout(() => {")
                    body = body.replace(b"fetch('/delayed').then(r => r.text()).then(text => {",
                                        b"nativeThen.call(fetch('/delayed'), r => { nativeThen.call(nativeText.call(r), text => {")
                    body = body.replace(b"});});</script>", b"}); }); });</script>")
                content_type = "text/html; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/fixture.html", sentinel
    finally:
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()


@contextmanager
def network_churn_webpage(transport):
    """Fast settled requests, no DOM mutation: network quiet alone must gate."""
    completed = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args): pass
        def do_GET(self):
            if self.path.startswith('/pulse'):
                body = b'ok'; kind = 'text/plain'
            else:
                request = "fetch('/pulse?' + n).then(r => r.text());" if transport == 'fetch' else "const x = new XMLHttpRequest(); x.open('GET', '/pulse?' + n); x.send();"
                # Offscreen WebKit throttles timers; MessageChannel keeps this
                # bounded fixture exercising real short requests, not timer gaps.
                body = ("<html><body>Stable DOM<script>addEventListener('load', () => {let n=0; "
                        "const channel=new MessageChannel(); const started=performance.now(); let last=started; "
                        "channel.port1.onmessage=()=>{const now=performance.now(); "
                        "if(now-started>=7000){channel.port1.close();channel.port2.close();return;} "
                        "if(now-last>=80){last=now;n++; " + request +
                        "} channel.port2.postMessage(0);}; channel.port2.postMessage(0);});</script></body></html>").encode()
                kind = 'text/html'
            self.send_response(200); self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(body))); self.end_headers()
            try:
                self.wfile.write(body); self.wfile.flush()
                if self.path.startswith('/pulse'): completed.append(time.monotonic())
            except (BrokenPipeError, ConnectionResetError): pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True); thread.start()
    try: yield f'http://127.0.0.1:{server.server_port}/fixture.html', completed
    finally:
        server.shutdown(); thread.join(timeout=3); server.server_close()
