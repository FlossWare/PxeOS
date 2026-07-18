# Deployment Guide

This guide covers deploying PxeOS in a production or lab environment. For development setup, see the main [README](../README.md).

**Important:** PxeOS is a pre-production project. See [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md) before deploying to production.

## Prerequisites

### Required

| Component | Version | Purpose |
|-----------|---------|---------|
| Python | 3.9+ (3.11+ recommended) | Runtime |
| DHCP server | dnsmasq or ISC DHCP | Points PXE clients to TFTP/iPXE |
| TFTP server | dnsmasq (built-in) or tftpd-hpa | Serves iPXE binary and boot scripts |
| Network access | Layer 2 to provisioning VLAN | PXE boot requires broadcast/DHCP relay |

### Optional

| Component | Purpose |
|-----------|---------|
| genisoimage / mkisofs / xorriso | Cloud-init config drive ISO creation |
| nginx / HAProxy | Reverse proxy for TLS termination, HA |
| systemd | Service management (unit file provided) |
| firewalld / iptables | Network access control |

## Installation

### From pip (recommended)

```bash
pip install pxeos
```

### From source

```bash
git clone https://github.com/FlossWare/PxeOS.git
cd PxeOS
pip install -e .
```

### Verify installation

```bash
pxeos --help
pxeos server start --help
```

## Configuration

### Config file

PxeOS reads configuration from a TOML file. The default location is `/etc/pxeos/pxeos.toml`.

```bash
# Create config directory
sudo mkdir -p /etc/pxeos/tls
sudo mkdir -p /var/lib/pxeos/distros
sudo mkdir -p /var/lib/tftpboot/pxeos

# Copy example config
sudo cp config/pxeos.toml /etc/pxeos/pxeos.toml
```

### Configuration reference

```toml
[server]
# Bind address (0.0.0.0 for all interfaces)
host = "0.0.0.0"
# HTTP/HTTPS port
port = 8443
# TLS certificate and key (recommended for production)
tls_cert = "/etc/pxeos/tls/cert.pem"
tls_key = "/etc/pxeos/tls/key.pem"

[paths]
# TFTP root directory (iPXE binaries and boot scripts)
tftp_root = "/var/lib/tftpboot/pxeos"
# Imported distro kernels and initrds
distro_root = "/var/lib/pxeos/distros"
# PxeOS data directory (profiles, hosts, state)
data_dir = "/var/lib/pxeos"

[auth]
# Enable API key authentication for protected endpoints
# Boot and autoinstall endpoints are always unauthenticated (PXE clients cannot authenticate)
enabled = false

[defaults]
os = "debian"
version = "12"
profile = "base"

[mnemonics]
# Custom distro aliases (in addition to built-ins)
# myrhel = { os_family = "fedora", vendor = "rhel", version = "9" }
```

### Directory layout

```
/etc/pxeos/
  pxeos.toml              # Main config
  tls/
    cert.pem              # TLS certificate
    key.pem               # TLS private key

/var/lib/pxeos/
  distros/                # Imported distro kernels/initrds
  profiles/               # Provisioning profiles
  hosts.toml              # Host-to-profile mappings
  state.json              # Runtime state (netboot status)

/var/lib/tftpboot/pxeos/  # TFTP-served files
  undionly.kpxe            # iPXE binary (BIOS)
  ipxe.efi                # iPXE binary (UEFI)
```

## Systemd Service

A systemd unit file is provided in `contrib/pxeos.service`.

### Setup

```bash
# Create a dedicated system user
sudo useradd --system --home-dir /var/lib/pxeos --shell /usr/sbin/nologin pxeos

# Set ownership
sudo chown -R pxeos:pxeos /var/lib/pxeos
sudo chown -R pxeos:pxeos /etc/pxeos

# TFTP directory may need to be readable by the TFTP server user
sudo chmod 755 /var/lib/tftpboot/pxeos

# Install the unit file
sudo cp contrib/pxeos.service /etc/systemd/system/
sudo systemctl daemon-reload

# Enable and start
sudo systemctl enable pxeos
sudo systemctl start pxeos

# Check status
sudo systemctl status pxeos
sudo journalctl -u pxeos -f
```

### Unit file details

The provided unit file (`contrib/pxeos.service`):
- Runs as the `pxeos` user/group (principle of least privilege)
- Restarts on failure with 5-second delay
- Sets `LimitNOFILE=65535` for high-concurrency scenarios
- Starts after `network.target`

## Firewall Rules

PxeOS requires the following network ports:

| Port | Protocol | Service | Direction | Notes |
|------|----------|---------|-----------|-------|
| 8443 | TCP | PxeOS HTTP/HTTPS API | Inbound | Configurable via `server.port` |
| 69 | UDP | TFTP | Inbound | External TFTP server (tftpd-hpa or dnsmasq) |
| 67-68 | UDP | DHCP | Inbound/Outbound | External DHCP server |
| 4011 | UDP | PXE proxy DHCP | Inbound | Only if using proxy DHCP mode |

### firewalld (Fedora, RHEL, CentOS)

A firewalld service definition is provided in `contrib/pxeos.firewalld.xml`.

```bash
# Install the service definition
sudo cp contrib/pxeos.firewalld.xml /etc/firewalld/services/pxeos.xml
sudo firewall-cmd --reload

# Add to the appropriate zone
sudo firewall-cmd --zone=internal --add-service=pxeos --permanent

# Also enable TFTP and DHCP if running on the same host
sudo firewall-cmd --zone=internal --add-service=tftp --permanent
sudo firewall-cmd --zone=internal --add-service=dhcp --permanent
sudo firewall-cmd --reload

# Verify
sudo firewall-cmd --zone=internal --list-services
```

### iptables

```bash
# PxeOS API
iptables -A INPUT -p tcp --dport 8443 -s 10.0.5.0/24 -j ACCEPT
iptables -A INPUT -p tcp --dport 8443 -j DROP

# TFTP (if running on same host)
iptables -A INPUT -p udp --dport 69 -s 10.0.5.0/24 -j ACCEPT

# DHCP (if running on same host)
iptables -A INPUT -p udp --dport 67:68 -j ACCEPT
```

### nftables

```bash
nft add rule inet filter input tcp dport 8443 ip saddr 10.0.5.0/24 accept
nft add rule inet filter input udp dport 69 ip saddr 10.0.5.0/24 accept
nft add rule inet filter input udp dport { 67, 68 } accept
```

**Important:** Restrict PxeOS access to the provisioning VLAN only. Do not expose PxeOS to the public internet or untrusted networks. PXE boot and autoinstall endpoints are unauthenticated by design (PXE clients cannot present credentials).

## SELinux

On SELinux-enforcing systems (Fedora, RHEL, CentOS), PxeOS may need additional context or policy adjustments.

### Check current mode

```bash
getenforce
# If "Enforcing", SELinux policies apply
```

### Required contexts

```bash
# Allow PxeOS to bind to its configured port
sudo semanage port -a -t http_port_t -p tcp 8443

# If 8443 is already defined (common), modify instead:
sudo semanage port -m -t http_port_t -p tcp 8443

# Set file contexts for PxeOS directories
sudo semanage fcontext -a -t httpd_sys_content_t "/var/lib/pxeos(/.*)?"
sudo semanage fcontext -a -t httpd_sys_rw_content_t "/var/lib/pxeos/state\.json"
sudo restorecon -Rv /var/lib/pxeos

# TFTP directory (if not already labeled)
sudo semanage fcontext -a -t tftpdir_t "/var/lib/tftpboot/pxeos(/.*)?"
sudo restorecon -Rv /var/lib/tftpboot/pxeos
```

### Common SELinux denials

If PxeOS fails to start or serve files, check the audit log:

```bash
# View recent denials
sudo ausearch -m avc -ts recent

# Generate a policy module for any denials
sudo ausearch -m avc -ts recent | audit2allow -M pxeos-local
sudo semodule -i pxeos-local.pp
```

### SELinux booleans

```bash
# Allow HTTPD scripts to connect to the network (if PxeOS fetches ISOs)
sudo setsebool -P httpd_can_network_connect 1

# Allow HTTPD to read user content
sudo setsebool -P httpd_read_user_content 1
```

**Note:** Creating a dedicated SELinux policy module for PxeOS is recommended for production. The `audit2allow` approach above is a stopgap; a proper policy should enumerate exactly what PxeOS needs.

## AppArmor

On AppArmor systems (Ubuntu, Debian), PxeOS typically runs without issues under the default `unconfined` profile. For hardened deployments:

```bash
# Check if AppArmor is active
sudo aa-status

# If creating a profile, PxeOS needs access to:
# - /etc/pxeos/** (read)
# - /var/lib/pxeos/** (read/write)
# - /var/lib/tftpboot/pxeos/** (read)
# - Network: tcp bind on configured port
# - /usr/bin/python3* (execute)
# - /tmp/** (read/write for ISO operations)
```

A sample AppArmor profile is not yet provided. Contributions welcome.

## TLS Setup

TLS is strongly recommended for all deployments. Autoinstall configs may contain password hashes and post-install scripts that run as root.

### Self-signed certificate (lab/testing)

```bash
# Generate a self-signed certificate
openssl req -x509 -newkey rsa:4096 -nodes \
  -keyout /etc/pxeos/tls/key.pem \
  -out /etc/pxeos/tls/cert.pem \
  -days 365 \
  -subj "/CN=pxeos.lab.local"

# Set permissions
sudo chown pxeos:pxeos /etc/pxeos/tls/*.pem
sudo chmod 600 /etc/pxeos/tls/key.pem
sudo chmod 644 /etc/pxeos/tls/cert.pem
```

### Let's Encrypt (production with public DNS)

```bash
# Using certbot
sudo certbot certonly --standalone -d pxeos.example.com

# Update pxeos.toml
# tls_cert = "/etc/letsencrypt/live/pxeos.example.com/fullchain.pem"
# tls_key = "/etc/letsencrypt/live/pxeos.example.com/privkey.pem"

# Note: PxeOS must be restarted to pick up renewed certificates
```

### Reverse proxy TLS termination (recommended for production)

Using nginx for TLS termination avoids certificate management within PxeOS:

```nginx
server {
    listen 443 ssl;
    server_name pxeos.example.com;

    ssl_certificate /etc/letsencrypt/live/pxeos.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/pxeos.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8443;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

When using a reverse proxy, disable TLS in `pxeos.toml` (comment out `tls_cert` and `tls_key`) and bind to `127.0.0.1` only.

## DHCP Configuration

PxeOS does not manage DHCP. You must configure your DHCP server to direct PXE clients to the TFTP server and iPXE binary.

### dnsmasq

```ini
# /etc/dnsmasq.d/pxeos.conf

# Enable TFTP
enable-tftp
tftp-root=/var/lib/tftpboot/pxeos

# PXE boot
dhcp-boot=undionly.kpxe

# UEFI support
dhcp-match=set:efi-x86_64,option:client-arch,7
dhcp-match=set:efi-x86_64,option:client-arch,9
dhcp-boot=tag:efi-x86_64,ipxe.efi

# Chain-load iPXE to PxeOS boot script
# Once iPXE is loaded, it fetches the boot script from PxeOS
dhcp-match=set:ipxe,175
dhcp-boot=tag:ipxe,http://pxeos-server:8443/api/v1/boot/${mac}
```

### ISC DHCP

```conf
# /etc/dhcp/dhcpd.conf

next-server pxeos-server-ip;

if exists user-class and option user-class = "iPXE" {
    filename "http://pxeos-server:8443/api/v1/boot/${mac}";
} elsif option client-architecture = 00:07 or option client-architecture = 00:09 {
    filename "ipxe.efi";
} else {
    filename "undionly.kpxe";
}
```

### iPXE binaries

Download iPXE binaries and place them in the TFTP root:

```bash
# Download pre-built iPXE binaries
curl -o /var/lib/tftpboot/pxeos/undionly.kpxe http://boot.ipxe.org/undionly.kpxe
curl -o /var/lib/tftpboot/pxeos/ipxe.efi http://boot.ipxe.org/ipxe.efi

# Or build from source with custom embedded script
git clone https://github.com/ipxe/ipxe.git
cd ipxe/src
make bin/undionly.kpxe EMBED=chainload.ipxe
make bin-x86_64-efi/ipxe.efi EMBED=chainload.ipxe
```

## Backup

### What to back up

| Path | Contents | Frequency |
|------|----------|-----------|
| `/etc/pxeos/pxeos.toml` | Server configuration | On change |
| `/var/lib/pxeos/profiles/` | Provisioning profiles | Daily |
| `/var/lib/pxeos/hosts.toml` | Host-to-profile mappings | Daily |
| `/var/lib/pxeos/state.json` | Netboot enable/disable state | Daily |
| `/etc/pxeos/tls/` | TLS certificates and keys | On change |
| `/var/lib/pxeos/distros/` | Imported kernel/initrd files | Weekly (can re-import from ISOs) |

### Example backup script

```bash
#!/bin/bash
# /usr/local/bin/backup-pxeos.sh
BACKUP_DIR="/var/backups/pxeos/$(date +%Y%m%d)"
mkdir -p "$BACKUP_DIR"

# Config and state (small, back up daily)
cp -a /etc/pxeos "$BACKUP_DIR/etc-pxeos"
cp -a /var/lib/pxeos/profiles "$BACKUP_DIR/profiles"
cp -a /var/lib/pxeos/hosts.toml "$BACKUP_DIR/hosts.toml"
cp -a /var/lib/pxeos/state.json "$BACKUP_DIR/state.json" 2>/dev/null

# Compress
tar czf "$BACKUP_DIR.tar.gz" -C "$(dirname "$BACKUP_DIR")" "$(basename "$BACKUP_DIR")"
rm -rf "$BACKUP_DIR"

# Retain 30 days
find /var/backups/pxeos/ -name "*.tar.gz" -mtime +30 -delete
```

Add to cron:
```bash
echo "0 2 * * * root /usr/local/bin/backup-pxeos.sh" | sudo tee /etc/cron.d/pxeos-backup
```

## High Availability

PxeOS does not have built-in HA. For environments requiring high availability:

### Active-passive with shared storage

```
                    ┌─────────────────┐
                    │   Load Balancer  │
                    │  (HAProxy/nginx) │
                    └────────┬────────┘
                             │
                    ┌────────┴────────┐
                    │                 │
              ┌─────┴─────┐   ┌──────┴────┐
              │  PxeOS A  │   │  PxeOS B  │
              │  (active)  │   │ (standby) │
              └─────┬─────┘   └──────┬────┘
                    │                 │
                    └────────┬────────┘
                             │
                    ┌────────┴────────┐
                    │  Shared Storage  │
                    │  (NFS / GlusterFS)│
                    └─────────────────┘
```

Requirements:
- Shared storage for `/var/lib/pxeos` (profiles, hosts, state)
- Shared storage or rsync for `/var/lib/pxeos/distros`
- Load balancer health check against `GET /api/v1/health`
- Only one instance should write to `state.json` at a time (no locking mechanism yet)

### HAProxy health check

```haproxy
backend pxeos
    option httpchk GET /api/v1/health
    server pxeos1 10.0.1.10:8443 check
    server pxeos2 10.0.1.11:8443 check backup
```

**Caveat:** PxeOS uses file-based state (`state.json`). Concurrent writes from multiple instances can cause data loss. For true HA, a database backend would be needed (not yet implemented).

## Troubleshooting

### PxeOS will not start

```bash
# Check service status and logs
sudo systemctl status pxeos
sudo journalctl -u pxeos --no-pager -n 50

# Common issues:
# - Port already in use: change server.port in pxeos.toml
# - Config file not found: check --config path
# - Permission denied: check file ownership (pxeos:pxeos)
# - TLS cert/key not found: check paths in pxeos.toml or comment out TLS
```

### Machine does not PXE boot

```bash
# 1. Verify DHCP is handing out the correct next-server and filename
tcpdump -i eth0 -n port 67 or port 68

# 2. Verify TFTP is serving iPXE binary
tftp pxeos-server -c get undionly.kpxe

# 3. Verify PxeOS is responding
curl -k https://pxeos-server:8443/api/v1/health

# 4. Verify boot script for the MAC address
curl -k https://pxeos-server:8443/api/v1/boot/aa:bb:cc:dd:ee:f1

# 5. Check if netboot is enabled for this host
curl -k https://pxeos-server:8443/api/v1/provision/aa:bb:cc:dd:ee:f1/netboot-status
```

### iPXE loads but install fails

```bash
# Verify the autoinstall config is valid
curl -k https://pxeos-server:8443/api/v1/autoinstall/aa:bb:cc:dd:ee:f1

# For Kickstart: validate with ksvalidator (from pykickstart)
curl -k https://pxeos-server:8443/api/v1/autoinstall/aa:bb:cc:dd:ee:f1 | ksvalidator -

# For Preseed: check syntax manually (no official validator)
# For Unattend.xml: validate against Microsoft's schema (Windows ADK)
```

### SELinux denials

```bash
# Check for AVC denials
sudo ausearch -m avc -ts recent | grep pxeos

# Temporarily set permissive to confirm SELinux is the issue
sudo setenforce 0
# Test, then re-enable:
sudo setenforce 1
```

### Firewall blocking

```bash
# Check if the port is reachable from a PXE client
nc -zv pxeos-server 8443

# Check firewalld
sudo firewall-cmd --list-all

# Check iptables
sudo iptables -L -n | grep 8443
```

### Log verbosity

PxeOS uses Python's `logging` module via uvicorn. Increase verbosity:

```bash
# Run with debug logging
pxeos server start --config /etc/pxeos/pxeos.toml --log-level debug

# Or set environment variable
UVICORN_LOG_LEVEL=debug pxeos server start --config /etc/pxeos/pxeos.toml
```
