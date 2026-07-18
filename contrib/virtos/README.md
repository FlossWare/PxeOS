# VirtOS Integration for PxeOS

This directory contains integration scripts and configurations for
connecting [VirtOS](https://github.com/FlossWare/VirtOS) to PxeOS,
enabling VirtOS to discover and proxy PxeOS REST API endpoints.

## Overview

VirtOS can use PxeOS as its PXE boot provisioning backend. The
integration consists of:

1. **Bridge script** (`virtos-pxeos`) -- discovers PxeOS and generates
   reverse proxy configuration
2. **Nginx config** (`nginx-pxeos.conf`) -- ready-to-use nginx proxy snippet
3. **HAProxy config** (`haproxy-pxeos.cfg`) -- ready-to-use HAProxy backend

## How VirtOS Discovers PxeOS

The bridge script supports three discovery methods (in priority order):

1. **Explicit arguments**: `--host` and `--port` on the command line
2. **Config file**: reads PxeOS TOML config for server address
3. **mDNS/DNS-SD**: automatic network discovery (requires `zeroconf`)
4. **Defaults**: falls back to `127.0.0.1:8443`

### Discovery via mDNS

Enable mDNS registration in your PxeOS config:

```toml
[discovery]
enabled = true
service_name = "pxeos"
```

Then start PxeOS. Other machines on the network can discover it:

```bash
./virtos-pxeos discover
```

Or use the CLI:

```bash
pxeos service info
pxeos service register
```

## Endpoint Mapping

VirtOS exposes PxeOS endpoints under a `/pxe/` prefix:

| VirtOS URL | PxeOS URL |
|---|---|
| `/api/v1/pxe/health` | `/api/v1/health` |
| `/api/v1/pxe/boot/{mac}` | `/api/v1/boot/{mac}` |
| `/api/v1/pxe/profiles` | `/api/v1/profiles` |
| `/api/v1/pxe/provision` | `/api/v1/provision` |
| `/api/v1/pxe/service-info` | `/api/v1/service-info` |

## Authentication Passthrough

Both proxy configurations forward the `Authorization` header from VirtOS
to PxeOS. If PxeOS has `auth_enabled = true`, clients must include a
valid API key in requests through VirtOS:

```bash
curl -H "Authorization: Bearer <pxeos-api-key>" \
     https://virtos-host/api/v1/pxe/health
```

## Configuration Options

### Nginx

Copy `nginx-pxeos.conf` into your nginx config and adjust the upstream:

```nginx
upstream pxeos-upstream {
    server 10.0.0.5:8443;  # Your PxeOS host
}
```

Include it in your VirtOS server block:

```nginx
server {
    listen 443 ssl;
    server_name virtos.example.com;

    include /etc/nginx/conf.d/pxeos.conf;

    # ... other VirtOS locations ...
}
```

### HAProxy

Add the backend from `haproxy-pxeos.cfg` to your HAProxy config and
add a frontend ACL:

```
frontend virtos
    bind *:443 ssl crt /etc/haproxy/certs/virtos.pem
    acl is_pxeos path_beg /api/v1/pxe/
    use_backend pxeos if is_pxeos
```

Adjust the server address:

```
backend pxeos
    server pxeos1 10.0.0.5:8443 check inter 10s
```

### Bridge Script

Generate configs dynamically:

```bash
# Generate nginx config pointing at a specific PxeOS
./virtos-pxeos nginx --url http://10.0.0.5:8443 -o /etc/nginx/conf.d/pxeos.conf

# Generate HAProxy config
./virtos-pxeos haproxy --url http://10.0.0.5:8443 -o /etc/haproxy/pxeos.cfg

# Check health
./virtos-pxeos health --url http://10.0.0.5:8443

# Auto-discover and show connection info
./virtos-pxeos discover --config /etc/pxeos/pxeos.toml
```

## Example: VirtOS + PxeOS Deployment

```
               +------------------+
               |     Clients      |
               +--------+---------+
                        |
               +--------v---------+
               |  VirtOS (nginx)  |
               |  /api/v1/pxe/*   |-----> PxeOS (10.0.0.5:8443)
               |  /api/v1/vm/*    |       /api/v1/*
               +------------------+
```

1. Install PxeOS on a provisioning server
2. Enable mDNS discovery in PxeOS config
3. On the VirtOS host, run `./virtos-pxeos discover` to find PxeOS
4. Generate proxy config: `./virtos-pxeos nginx -o /etc/nginx/conf.d/pxeos.conf`
5. Reload nginx: `systemctl reload nginx`
6. VirtOS clients can now access PxeOS via `/api/v1/pxe/*`
