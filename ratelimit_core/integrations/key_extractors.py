from __future__ import annotations

from typing import Callable

from starlette.requests import Request

KeyExtractor = Callable[[Request], str]


def get_client_ip(
    request: Request,
    trusted_proxies: set[str] | None = None,
    proxy_count: int | None = None,
) -> str:
    """
    Extract verified client IP address.
    Protects against IP spoofing when behind reverse proxies (Cloudflare, AWS ALB, NGINX).

    - If `trusted_proxies` is provided: traverses `X-Forwarded-For` right-to-left
      until the first untrusted IP is found.
    - If `proxy_count` is provided: selects the IP at `-(proxy_count)` from `X-Forwarded-For`.
    - Otherwise: safely checks `X-Real-IP`, then leftmost `X-Forwarded-For`, then socket client.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        ips = [ip.strip() for ip in forwarded.split(",") if ip.strip()]
        if ips:
            if trusted_proxies:
                # Iterate from right (closest proxy) to left
                for ip in reversed(ips):
                    if ip not in trusted_proxies:
                        return ip
                return ips[0]
            elif proxy_count is not None and len(ips) >= proxy_count:
                return ips[-proxy_count]
            else:
                return ips[0]

    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()

    if request.client and request.client.host:
        return request.client.host

    return "127.0.0.1"


def client_ip_extractor(
    trusted_proxies: set[str] | None = None,
    proxy_count: int | None = None,
) -> KeyExtractor:
    """
    Factory for a secure client IP extractor configured with trusted proxies.
    """
    def _extractor(request: Request) -> str:
        return get_client_ip(request, trusted_proxies=trusted_proxies, proxy_count=proxy_count)

    return _extractor


def header_extractor(header_name: str, fallback_ip: bool = True) -> KeyExtractor:
    """
    Generate an extractor that reads a specified HTTP header (e.g., 'X-API-Key', 'Authorization').
    """
    lower_name = header_name.lower()

    def _extractor(request: Request) -> str:
        val = request.headers.get(lower_name)
        if val:
            return f"header:{lower_name}:{val.strip()}"
        if fallback_ip:
            return f"ip:{get_client_ip(request)}"
        return f"header:{lower_name}:anonymous"

    return _extractor


def path_and_ip_extractor(request: Request) -> str:
    """
    Combine route path and client IP for endpoint-specific limits.
    """
    ip = get_client_ip(request)
    return f"{request.method}:{request.url.path}:{ip}"

