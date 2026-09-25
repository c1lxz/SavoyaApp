"""Protect session validation while preserving the server's existing nginx paths."""
from __future__ import annotations

import argparse
from pathlib import Path


def harden(config: str) -> str:
    if "zone=savoya_session_validation:10m" in config:
        return config
    marker = "    upstream savoya_backend {"
    if config.count(marker) != 1:
        raise ValueError("Expected one savoya_backend upstream")
    config = config.replace(marker, """    # Bound validation traffic from older clients with a polling feedback loop.
    map $http_authorization $savoya_session_limit_key {
        "" $binary_remote_addr;
        default $http_authorization;
    }
    limit_req_zone $savoya_session_limit_key zone=savoya_session_validation:10m rate=2r/s;

""" + marker, 1)
    marker = "        location /api/ {"
    if config.count(marker) != 1:
        raise ValueError("Expected one /api/ location")
    locations = []
    for route in ("/user/me", "/api/user/me"):
        if f"location = {route} " in config:
            raise ValueError(f"Existing exact location requires review: {route}")
        locations.append(f"""        location = {route} {{
            limit_req zone=savoya_session_validation burst=3 nodelay;
            limit_req_status 429;
            limit_req_log_level warn;
            proxy_pass http://savoya_backend;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Host $host;
            proxy_set_header X-Forwarded-Port $server_port;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_connect_timeout 5s;
            proxy_send_timeout 30s;
            proxy_read_timeout 30s;
        }}

""")
    return config.replace(marker, "".join(locations) + marker, 1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    original = args.config.read_text(encoding="utf-8-sig")
    updated = harden(original)
    if updated != original:
        args.config.write_text(updated, encoding="utf-8")
    print("Session validation limits configured")
