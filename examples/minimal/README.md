# Minimal PxeOS Example

A complete working setup that provisions a single Fedora 42 Server machine via PXE boot. Follow this walkthrough to go from zero to a working PxeOS server in under 30 minutes.

**What this example covers:**

- Installing PxeOS
- Importing a Fedora 42 distro
- Creating a provisioning profile
- Registering a host by MAC address
- Starting the PxeOS server
- Configuring DHCP to point PXE clients at PxeOS

**What this example does NOT cover:**

- TLS (disabled for simplicity -- enable it for anything beyond a lab)
- Authentication (disabled for simplicity)
- Multiple distros or OS families
- UEFI boot (this example uses BIOS/legacy PXE)
- Production hardening (see [docs/DEPLOYMENT.md](../../docs/DEPLOYMENT.md))

> **Warning:** PxeOS is alpha software. It has not been validated with real PXE-booting hardware. See the [Alpha Status & Known Limitations](../../README.md#alpha-status--known-limitations) section in the main README before relying on this for anything important.

## Prerequisites

- A Linux server (Fedora, RHEL, Debian, or Ubuntu) that will run PxeOS
- Python 3.9 or later (`python3 --version`)
- A DHCP server on the provisioning network (dnsmasq recommended)
- A TFTP server (dnsmasq includes one, or use tftpd-hpa)
- A Fedora 42 Server ISO or access to a Fedora mirror
- A target machine that supports PXE boot (on the same network/VLAN)
- Root/sudo access on the PxeOS server

## Step 1: Install PxeOS (2 minutes)

```bash
pip install pxeos

# Verify
pxeos --version
pxeos --help
```

Or install from source:

```bash
git clone https://github.com/FlossWare/PxeOS.git
cd PxeOS
pip install -e .
```

## Step 2: Create directory structure (1 minute)

```bash
sudo mkdir -p /srv/pxeos/distros
sudo mkdir -p /srv/pxeos/profiles
sudo mkdir -p /srv/tftp
```

## Step 3: Copy configuration files (2 minutes)

Copy the example configs from this directory to the PxeOS data directory:

```bash
# Copy server config
sudo cp examples/minimal/pxeos.toml /srv/pxeos/pxeos.toml

# Copy host rules
sudo cp examples/minimal/hosts.toml /srv/pxeos/hosts.toml

# Copy the profile
sudo cp examples/minimal/profiles/fedora-server.toml /srv/pxeos/profiles/fedora-server.toml
```

If you cloned the repo, run the above from the repo root. Otherwise, download the files individually:

```bash
REPO="https://raw.githubusercontent.com/FlossWare/PxeOS/main"
sudo curl -o /srv/pxeos/pxeos.toml "$REPO/examples/minimal/pxeos.toml"
sudo curl -o /srv/pxeos/hosts.toml "$REPO/examples/minimal/hosts.toml"
sudo mkdir -p /srv/pxeos/profiles
sudo curl -o /srv/pxeos/profiles/fedora-server.toml "$REPO/examples/minimal/profiles/fedora-server.toml"
```

## Step 4: Edit the host rule (2 minutes)

Open `/srv/pxeos/hosts.toml` and replace the placeholder MAC address with the actual MAC of the machine you want to PXE-boot:

```bash
sudo vi /srv/pxeos/hosts.toml
```

Change `aa:bb:cc:dd:ee:f1` to your machine's MAC address (lowercase, colon-separated). You can find the MAC in the machine's BIOS/UEFI settings or by running `ip link` if an OS is already installed.

## Step 5: Edit the profile (3 minutes)

Open `/srv/pxeos/profiles/fedora-server.toml` and make two edits:

```bash
sudo vi /srv/pxeos/profiles/fedora-server.toml
```

1. **Set `install_url`** to a Fedora 42 mirror close to you (or a local mirror if you have one). The default points to the public Fedora CDN, which works but may be slow for PXE installs.

2. **Set `PXEOS_SERVER`** in the `post_scripts` entry to the IP address or hostname of your PxeOS server. Also update the MAC address in that URL to match your target machine. This script runs at the end of installation to disable PXE netboot so the machine boots from disk on the next reboot.

## Step 6: Import the Fedora 42 distro (5 minutes)

PxeOS needs the kernel and initrd from the Fedora installer. You can import from an ISO or from a mirror URL.

**Option A: Import from ISO** (if you have a Fedora 42 Server ISO downloaded):

```bash
sudo pxeos import --iso /path/to/Fedora-Server-dvd-x86_64-42-1.1.iso \
    --distro fedora42 \
    --config /srv/pxeos/pxeos.toml
```

**Option B: Import from mirror URL** (downloads kernel and initrd only, no full ISO needed):

```bash
sudo pxeos import \
    --url https://download.fedoraproject.org/pub/fedora/linux/releases/42/Server/x86_64/os/ \
    --distro fedora42 \
    --config /srv/pxeos/pxeos.toml
```

Either command extracts the kernel (`vmlinuz`) and initrd (`initrd.img`) into `/srv/pxeos/distros/`.

**Dry run first** (optional -- shows what would happen without extracting anything):

```bash
pxeos import \
    --url https://download.fedoraproject.org/pub/fedora/linux/releases/42/Server/x86_64/os/ \
    --distro fedora42 \
    --config /srv/pxeos/pxeos.toml \
    --dry-run
```

## Step 7: Download iPXE binaries (2 minutes)

PXE clients load a small iPXE bootloader via TFTP, which then fetches the real boot script from PxeOS over HTTP. Download the pre-built iPXE binary:

```bash
sudo curl -o /srv/tftp/undionly.kpxe http://boot.ipxe.org/undionly.kpxe
```

For UEFI boot (not covered in this example but useful to have):

```bash
sudo curl -o /srv/tftp/ipxe.efi http://boot.ipxe.org/ipxe.efi
```

## Step 8: Configure DHCP (5 minutes)

Your DHCP server must tell PXE clients two things: where to find the TFTP server and what file to load. Here is a dnsmasq example.

Create or edit `/etc/dnsmasq.d/pxeos.conf`:

```ini
# Enable built-in TFTP server
enable-tftp
tftp-root=/srv/tftp

# BIOS PXE clients: load iPXE via TFTP
dhcp-boot=undionly.kpxe

# Once iPXE is running, chain-load the PxeOS boot script.
# iPXE identifies itself via option 175.
dhcp-match=set:ipxe,175
dhcp-boot=tag:ipxe,http://PXEOS_SERVER:8443/api/v1/boot/${mac}
```

Replace `PXEOS_SERVER` with the IP address of your PxeOS server.

Restart dnsmasq:

```bash
sudo systemctl restart dnsmasq
```

If you are using ISC DHCP instead, see the [Deployment Guide](../../docs/DEPLOYMENT.md#isc-dhcp) for equivalent configuration.

## Step 9: Start PxeOS (1 minute)

```bash
pxeos server start --config /srv/pxeos/pxeos.toml
```

Leave this running in a terminal (or use `systemd` -- see [Deployment Guide](../../docs/DEPLOYMENT.md#systemd-service)).

Verify it is responding:

```bash
# In another terminal:
curl http://localhost:8443/api/v1/health
# Expected: {"status": "ok", ...}

# Check the boot script for your MAC:
curl http://localhost:8443/api/v1/boot/aa:bb:cc:dd:ee:f1
# Expected: iPXE script with kernel/initrd URLs

# Check the autoinstall config:
curl http://localhost:8443/api/v1/autoinstall/aa:bb:cc:dd:ee:f1
# Expected: Kickstart config for Fedora
```

Replace `aa:bb:cc:dd:ee:f1` with your target machine's MAC address.

## Step 10: PXE-boot the target machine (5 minutes)

1. Power on the target machine.
2. Enter the BIOS/UEFI boot menu (usually F12, F2, or Del during POST).
3. Select "Network Boot" or "PXE Boot."
4. The machine should:
   - Get an IP via DHCP
   - Download `undionly.kpxe` via TFTP
   - iPXE fetches the boot script from PxeOS
   - Kernel and initrd load
   - Anaconda (Fedora installer) starts
   - The Kickstart config from PxeOS drives the automated install
5. After installation, the post-install script disables PXE netboot.
6. The machine reboots into the newly installed Fedora.

## Verification

After installation completes, verify the machine boots from disk (not PXE) on subsequent reboots.

If you need to re-provision, re-enable PXE boot:

```bash
# Via CLI (talks to the running PxeOS server):
pxeos host enable-netboot aa:bb:cc:dd:ee:f1

# Or via API:
curl -X POST http://PXEOS_SERVER:8443/api/v1/provision/aa:bb:cc:dd:ee:f1/enable-netboot
```

## Troubleshooting

**Machine does not PXE boot at all:**
- Verify PXE boot is enabled in BIOS/UEFI.
- Check that DHCP is providing `next-server` and `filename`: `tcpdump -i eth0 -n port 67`.
- Verify TFTP is serving the iPXE binary: `tftp localhost -c get undionly.kpxe`.

**iPXE loads but cannot reach PxeOS:**
- Check firewall rules -- port 8443 must be open from the provisioning network.
- Verify PxeOS is running: `curl http://PXEOS_SERVER:8443/api/v1/health`.
- Check dnsmasq config points at the correct PxeOS IP.

**Installer starts but fails:**
- Check the autoinstall config: `curl http://PXEOS_SERVER:8443/api/v1/autoinstall/MAC`.
- For Kickstart issues, validate with: `pip install pykickstart && ksvalidator /tmp/ks.cfg`.
- Check that `install_url` in the profile points to a valid Fedora mirror.

**Machine re-enters PXE loop after install:**
- The post-install script may have failed. Check that `PXEOS_SERVER` was replaced with the actual IP.
- Manually disable netboot: `curl -X POST http://PXEOS_SERVER:8443/api/v1/provision/MAC/disable-netboot`.

For more troubleshooting steps, see [docs/DEPLOYMENT.md](../../docs/DEPLOYMENT.md#troubleshooting).

## Files in this example

| File | Purpose |
|------|---------|
| `pxeos.toml` | Server configuration (bind address, paths, no TLS) |
| `hosts.toml` | Maps one MAC address to the `fedora-server` profile |
| `profiles/fedora-server.toml` | Fedora 42 Server provisioning profile (packages, network, post-scripts) |

## Next steps

- Add more host rules for additional machines (by MAC, hostname pattern, or subnet).
- Create profiles for other OS families (Debian, Ubuntu, FreeBSD, etc.).
- Enable TLS for transport security.
- Enable API key authentication.
- Set up systemd for automatic startup.
- See the main [README](../../README.md) for the full feature set.
