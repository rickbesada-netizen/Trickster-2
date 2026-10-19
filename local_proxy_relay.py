"""
Local proxy relay — works around a known limitation where Playwright's
automatic proxy-authentication handling doesn't reliably work with
launch_persistent_context() (the mode this whole project uses for
extension support), even though the same proxy works fine in a normal
browser or an ephemeral (non-persistent) Playwright context.

The fix: instead of pointing Chromium directly at an authenticated proxy
(which triggers the broken auth flow), we run a tiny local proxy that
Chromium sees as requiring NO authentication at all. This local relay does
the real authentication to your actual proxy provider itself, invisibly,
by injecting a Proxy-Authorization header before relaying traffic through.
Chromium never has to handle a proxy login challenge, so the bug never gets
a chance to trigger.

This is a standard, well-established workaround for this exact class of
problem — not a hack specific to this project.
"""

import base64
import socket
import threading


def _relay(src: socket.socket, dst: socket.socket):
    """Pipes raw bytes one direction until either side closes. Used after
    a CONNECT tunnel is established — from this point on we're just
    forwarding opaque (usually TLS-encrypted) bytes, never inspecting them."""
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except OSError:
        pass
    finally:
        try:
            dst.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def _read_headers(sock: socket.socket) -> bytes:
    """Reads until the blank line that ends an HTTP request's headers."""
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            break
        buf += chunk
    return buf


def _handle_client(client_sock: socket.socket, upstream_host: str, upstream_port: int, auth_header: str):
    try:
        request = _read_headers(client_sock)
        if not request:
            client_sock.close()
            return

        request_line = request.split(b"\r\n", 1)[0].decode(errors="replace")
        is_connect = request_line.upper().startswith("CONNECT ")

        upstream_sock = socket.create_connection((upstream_host, upstream_port), timeout=15)

        if is_connect:
            # HTTPS: forward the same CONNECT line, inject auth, relay the
            # "200 Connection Established" back, then become a dumb pipe —
            # everything after this is opaque TLS between Chromium and the
            # real destination, we never see inside it.
            head, _, rest = request.partition(b"\r\n\r\n")
            lines = head.split(b"\r\n")
            lines.append(f"Proxy-Authorization: {auth_header}".encode())
            new_request = b"\r\n".join(lines) + b"\r\n\r\n"
            upstream_sock.sendall(new_request)

            response = upstream_sock.recv(4096)
            status_line = response.split(b"\r\n", 1)[0].decode(errors="replace")
            if not status_line.startswith("HTTP/1.") or " 200 " not in status_line:
                # Upstream rejected our credentials (or something else went
                # wrong) — this is exactly what surfaces in Chrome as "the
                # proxy 127.0.0.1:PORT requires a username and password",
                # which is misleading since the relay itself never asks for
                # one; it's really upstream_host:upstream_port saying no.
                # Printed here instead of silently forwarded so the real
                # cause (bad creds, IP not whitelisted, wrong port/auth
                # mode, expired plan, etc.) is visible in the console
                # instead of just a mystery browser popup.
                print(f"[proxy-relay] {upstream_host}:{upstream_port} rejected the request: {status_line!r} "
                      f"— check the username/password for this proxy, or whether this endpoint needs IP "
                      f"whitelisting instead of user/pass auth (common with residential proxy providers).")
            client_sock.sendall(response)

            t1 = threading.Thread(target=_relay, args=(client_sock, upstream_sock), daemon=True)
            t2 = threading.Thread(target=_relay, args=(upstream_sock, client_sock), daemon=True)
            t1.start()
            t2.start()
            t1.join()
            t2.join()
        else:
            # Plain HTTP (rare nowadays, but handled for completeness):
            # inject the header into the request itself, forward once,
            # relay the response back.
            head, _, rest = request.partition(b"\r\n\r\n")
            lines = head.split(b"\r\n")
            lines.insert(1, f"Proxy-Authorization: {auth_header}".encode())
            new_request = b"\r\n".join(lines) + b"\r\n\r\n" + rest
            upstream_sock.sendall(new_request)

            t1 = threading.Thread(target=_relay, args=(client_sock, upstream_sock), daemon=True)
            t2 = threading.Thread(target=_relay, args=(upstream_sock, client_sock), daemon=True)
            t1.start()
            t2.start()
            t1.join()
            t2.join()
    except Exception as e:
        # Was a bare `except Exception: pass` — any connection failure
        # (upstream host unreachable, wrong port, timeout, etc.) vanished
        # silently, leaving only a confusing browser-side symptom to debug
        # from. Printed now so a dead/misconfigured proxy shows up here
        # instead of only as an unexplained popup or hung tab.
        print(f"[proxy-relay] error talking to {upstream_host}:{upstream_port}: {e}")
    finally:
        try:
            client_sock.close()
        except OSError:
            pass


def start_local_proxy_relay(upstream_host: str, upstream_port: int, username: str, password: str) -> int:
    """Starts the relay on a free local port and returns that port
    immediately (the server runs in a background daemon thread — it dies
    automatically when the whole process exits, no explicit shutdown needed
    for a per-launch, per-profile relay like this)."""
    auth_header = "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()

    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind(("127.0.0.1", 0))
    local_port = server_sock.getsockname()[1]
    server_sock.listen(128)

    def serve():
        while True:
            try:
                client_sock, _ = server_sock.accept()
            except OSError:
                return
            threading.Thread(
                target=_handle_client,
                args=(client_sock, upstream_host, upstream_port, auth_header),
                daemon=True,
            ).start()

    threading.Thread(target=serve, daemon=True).start()
    return local_port
