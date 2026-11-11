"""Sled Pack: `network` — Atomic network interface, route, socket/port, ping, and Tailscale tools (`ip_addr`, `ip_route`, `ss_ports`, `ping`, `tailscale_status`)."""

from __future__ import annotations

import json
import logging
import socket
from typing import TYPE_CHECKING, Any

from sled.tools import ToolSpec
from sled.tools._exec import run_cmd, which_bin

if TYPE_CHECKING:
    from mcp.server import MCPServer

logger = logging.getLogger("sled.tools.network")

PACK = "network"


def ip_addr(interface: str = "") -> dict[str, Any]:
    """Returns network interfaces, IPv4/IPv6 addresses, MAC addresses, and link state (`ip -j addr`).

    Args:
        interface: Optional specific interface name (e.g. `wlan0`, `eth0`, `tailscale0`).
    """
    cmd = ["ip", "-j", "addr"]
    if interface.strip():
        cmd.extend(["show", interface.strip()])
    code, out, err = run_cmd(cmd, timeout=5.0)
    if code != 0:
        return {"status": "error", "error": err or out}

    try:
        interfaces = json.loads(out) if out else []
    except json.JSONDecodeError:
        interfaces = []

    return {
        "status": "ok",
        "count": len(interfaces),
        "interfaces": interfaces,
    }


def ip_route() -> dict[str, Any]:
    """Returns the kernel IP routing table (`ip -j route`)."""
    code, out, err = run_cmd(["ip", "-j", "route"], timeout=5.0)
    if code != 0:
        return {"status": "error", "error": err or out}

    try:
        routes = json.loads(out) if out else []
    except json.JSONDecodeError:
        routes = []

    return {
        "status": "ok",
        "count": len(routes),
        "routes": routes,
    }


def ss_ports(protocol: str = "all", compact: bool = True) -> dict[str, Any]:
    """Lists listening TCP and UDP sockets/ports and owning processes (`ss -tulnp`).

    Args:
        protocol: `all` (default), `tcp`, or `udp`.
        compact: Return tabular `columns` and `rows` to minimize token overhead (default True).
    """
    proto = protocol.strip().lower()
    flags = "-tlnp" if proto == "tcp" else ("-ulnp" if proto == "udp" else "-tulnp")
    code, out, err = run_cmd(["ss", flags], timeout=5.0)
    if code != 0:
        return {"status": "error", "error": err or out}

    lines = out.splitlines()
    if compact:
        columns = ["netid", "state", "local_address", "peer_address", "process"]
        rows: list[list[str]] = []
        for line in lines[1:]:
            parts = line.split(None, 6)
            if len(parts) >= 5:
                rows.append(
                    [
                        parts[0],
                        parts[1],
                        parts[4],
                        parts[5] if len(parts) > 5 else "*",
                        parts[6] if len(parts) > 6 else "",
                    ]
                )
        return {
            "status": "ok",
            "protocol": proto,
            "count": len(rows),
            "columns": columns,
            "rows": rows,
        }

    sockets: list[dict[str, str]] = []
    for line in lines[1:]:
        parts = line.split(None, 6)
        if len(parts) >= 5:
            sockets.append(
                {
                    "netid": parts[0],
                    "state": parts[1],
                    "local_address": parts[4],
                    "peer_address": parts[5] if len(parts) > 5 else "",
                    "process": parts[6] if len(parts) > 6 else "",
                }
            )

    return {
        "status": "ok",
        "protocol": proto,
        "count": len(sockets),
        "sockets": sockets,
    }


def ping(host: str = "1.1.1.1", count: int = 2) -> dict[str, Any]:
    """Checks DNS resolution and ICMP ping reachability to a target host.

    Args:
        host: Hostname or IP address to test (default `1.1.1.1`).
        count: Number of ICMP ping packets to send (default 2, max 5).
    """
    target = host.strip() or "1.1.1.1"
    count = max(1, min(int(count), 5))

    resolved_ips: list[str] = []
    dns_error: str | None = None
    try:
        infos = socket.getaddrinfo(target, None)
        for info in infos:
            ip = str(info[4][0])
            if ip not in resolved_ips:
                resolved_ips.append(ip)
    except OSError as exc:
        dns_error = str(exc)

    ping_code, ping_out, ping_err = run_cmd(
        ["ping", "-c", str(count), "-W", "2", target], timeout=10.0
    )

    return {
        "status": "ok" if ping_code == 0 or resolved_ips else "degraded",
        "host": target,
        "resolved_ips": resolved_ips,
        "dns_error": dns_error,
        "ping_reachable": ping_code == 0,
        "ping_output": ping_out or ping_err,
    }


def tailscale_status() -> dict[str, Any]:
    """Returns Tailscale mesh VPN connection state, self DNS/IPs, and peer nodes (`tailscale status --json`)."""
    if not which_bin("tailscale"):
        return {"status": "error", "error": "`tailscale` binary not found in PATH."}

    code, out, err = run_cmd(["tailscale", "status", "--json"], timeout=5.0)
    if code != 0:
        return {"status": "error", "error": err or out}

    try:
        ts_json = json.loads(out)
    except json.JSONDecodeError:
        return {"status": "error", "error": "Failed to parse tailscale status JSON."}

    peers: list[dict[str, Any]] = []
    for pinfo in (ts_json.get("Peer") or {}).values():
        if isinstance(pinfo, dict):
            peers.append(
                {
                    "hostname": pinfo.get("HostName"),
                    "dns_name": pinfo.get("DNSName"),
                    "ips": pinfo.get("TailscaleIPs", []),
                    "online": pinfo.get("Online"),
                    "os": pinfo.get("OS"),
                }
            )

    return {
        "status": "ok",
        "backend_state": ts_json.get("BackendState"),
        "self_dns_name": ts_json.get("Self", {}).get("DNSName"),
        "tailscale_ips": ts_json.get("TailscaleIPs", []),
        "peers": peers,
    }


def dns_lookup(domain: str, query_type: str = "A") -> dict[str, Any]:
    """Queries DNS records (A, AAAA, CNAME, MX, TXT) for a domain or hostname.

    Args:
        domain: Domain name or host to query (e.g. `github.com`).
        query_type: DNS record type: `A` (default), `AAAA`, `CNAME`, `MX`, `TXT`, `NS`, or `ANY`.
    """
    dom = domain.strip()
    qtype = query_type.strip().upper()
    if not dom:
        return {"status": "error", "error": "Domain must not be empty."}

    if which_bin("dig"):
        code, out, _ = run_cmd(["dig", "+noall", "+answer", "+stats", dom, qtype])
        if code == 0 and out:
            records: list[str] = []
            for line in out.splitlines():
                line = line.strip()
                if line and not line.startswith(";;"):
                    records.append(line)
            return {
                "status": "ok",
                "engine": "dig",
                "domain": dom,
                "query_type": qtype,
                "records": records,
                "raw": out,
            }

    try:
        family = socket.AF_INET6 if qtype == "AAAA" else socket.AF_INET
        addrs = socket.getaddrinfo(dom, None, family)
        ips = sorted({str(res[4][0]) for res in addrs})
        return {
            "status": "ok",
            "engine": "socket",
            "domain": dom,
            "query_type": qtype,
            "ips": ips,
        }
    except OSError as exc:
        return {"status": "error", "domain": dom, "error": str(exc)}


def http_probe(
    url: str,
    method: str = "GET",
    timeout: int = 5,
    max_body_chars: int = 500,
) -> dict[str, Any]:
    """Performs a lightweight HTTP/HTTPS probe returning status code, latency, and response headers.

    Args:
        url: Target URL (e.g. `http://localhost:8080`, `https://example.com`).
        method: Request method: `GET` (default) or `HEAD`.
        timeout: Timeout in seconds (default 5, max 30).
        max_body_chars: Maximum characters of response body to return (default 500).
    """
    import ssl
    import time
    import urllib.error
    import urllib.request

    target_url = url.strip()
    if not target_url.startswith(("http://", "https://")):
        target_url = f"http://{target_url}"

    timeout = max(1, min(int(timeout), 30))
    req_method = method.strip().upper()
    if req_method not in ("GET", "HEAD"):
        req_method = "GET"

    req = urllib.request.Request(
        target_url,
        headers={"User-Agent": "Sled-Probe/0.1.0"},
        method=req_method,
    )

    t0 = time.perf_counter()
    try:
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
            headers = dict(resp.headers)
            body = ""
            if req_method == "GET":
                raw = resp.read(max_body_chars + 1)
                body = raw[:max_body_chars].decode("utf-8", errors="replace")
            return {
                "status": "ok",
                "url": resp.url,
                "status_code": resp.status,
                "reason": resp.reason,
                "elapsed_ms": elapsed_ms,
                "headers": headers,
                "body_preview": body,
            }
    except urllib.error.HTTPError as exc:
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
        return {
            "status": "http_error",
            "url": target_url,
            "status_code": exc.code,
            "reason": exc.reason,
            "elapsed_ms": elapsed_ms,
            "headers": dict(exc.headers),
        }
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
        return {
            "status": "error",
            "url": target_url,
            "elapsed_ms": elapsed_ms,
            "error": str(exc),
        }


TOOLS = [
    ToolSpec(
        name="ip_addr",
        module="network",
        description="Returns network interfaces, IPv4/IPv6 addresses, and link state (ip -j addr).",
        handler=ip_addr,
        pack="network",
    ),
    ToolSpec(
        name="ip_route",
        module="network",
        description="Returns the kernel IP routing table (ip -j route).",
        handler=ip_route,
        pack="network",
    ),
    ToolSpec(
        name="ss_ports",
        module="network",
        description="Lists listening TCP and UDP sockets/ports and their owning processes (ss -tulnp).",
        handler=ss_ports,
        pack="network",
    ),
    ToolSpec(
        name="ping",
        module="network",
        description="Checks DNS resolution and sends ICMP ping packets to test host reachability.",
        handler=ping,
        pack="network",
    ),
    ToolSpec(
        name="tailscale_status",
        module="network",
        description="Returns Tailscale VPN status, local Tailscale IPs, and connected mesh peers.",
        handler=tailscale_status,
        pack="network",
    ),
    ToolSpec(
        name="dns_lookup",
        module="network",
        description="Queries DNS records (A, AAAA, CNAME, MX, TXT) for a domain or hostname.",
        handler=dns_lookup,
        pack="network",
    ),
    ToolSpec(
        name="http_probe",
        module="network",
        description="Performs a lightweight HTTP/HTTPS probe returning status code, latency, and headers.",
        handler=http_probe,
        pack="network",
    ),
]


def register(mcp: MCPServer) -> None:
    """Register network tools with MCPServer."""
    for spec in TOOLS:
        mcp.tool(name=spec.name, description=spec.description)(spec.handler)
