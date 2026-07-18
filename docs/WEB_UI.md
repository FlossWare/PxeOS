# PxeOS Web UI

PxeOS includes a server-rendered web interface built with FastAPI, Jinja2 templates, and htmx for dynamic interactions. The web UI is available at `/web/` when the PxeOS server is running.

## Accessing the Web UI

Start the server and open the web UI in a browser:

```bash
pxeos server start --config config/pxeos.toml
# Open http://localhost:8443/web/ in your browser
```

## Navigation

The web UI uses a sidebar layout with a fixed navigation panel on the left and the main content area on the right. The sidebar shows the FlossWare logo and "PxeOS" branding, with navigation links for all pages. The active page is highlighted with a blue left border.

```
+------------------+-------------------------------------------+
|  [FlossWare]     |                                           |
|   PxeOS          |              Main Content                 |
|                  |                                           |
|  > Dashboard     |                                           |
|    Distros       |                                           |
|    Profiles      |                                           |
|    Host Rules    |                                           |
|    Cloud-Init    |                                           |
|    Import        |                                           |
+------------------+-------------------------------------------+
```

On screens narrower than 768px the sidebar is hidden and only the main content area is shown.

## Pages

### Dashboard (`/web/`)

The landing page shows an overview of the PxeOS instance.

**Stats cards** -- Four metric tiles across the top showing counts of:
- Imported Distros
- Profiles
- Host Rules
- OS Plugins

**Loaded Plugins** -- A table listing each registered OS family plugin and its type badge:
- Linux plugins (fedora, debian, ubuntu, suse, arch) show a blue "Linux" badge
- BSD plugins (freebsd, openbsd, netbsd) show a green "BSD" badge
- Windows plugin shows a yellow "Windows" badge

**Server Info** -- A table showing:
- Version (PxeOS version)
- Host (server bind address)
- Port (server port)
- TLS (Enabled/Disabled)

```
+-------------------------------------------------------+
|  Dashboard                                            |
|                                                       |
|  +----------+ +----------+ +----------+ +----------+ |
|  |    3     | |    5     | |    12    | |    10    | |
|  | Distros  | | Profiles | | Host     | | OS       | |
|  |          | |          | | Rules    | | Plugins  | |
|  +----------+ +----------+ +----------+ +----------+ |
|                                                       |
|  Loaded Plugins                                       |
|  OS FAMILY     TYPE                                   |
|  fedora        [Linux]                                |
|  debian        [Linux]                                |
|  freebsd       [BSD]                                  |
|  windows       [Windows]                              |
|                                                       |
|  Server Info                                          |
|  Version       0.9                                    |
|  Host          0.0.0.0                                |
|  Port          8443                                   |
|  TLS           Disabled                               |
+-------------------------------------------------------+
```

### Distros (`/web/distros`)

Lists all imported distribution directories with their filesystem paths.

**Table columns:**
- Name -- the distro directory name (e.g., `fedora-42-x86_64`)
- Path -- the full filesystem path
- Actions -- a red "Delete" button that removes the distro directory (with confirmation dialog via htmx)

When no distros are imported, a message links to the Import page.

```
+-------------------------------------------------------+
|  Imported Distros                                     |
|                                                       |
|  NAME                    PATH               ACTIONS   |
|  fedora-42-x86_64        /srv/pxeos/...     [Delete]  |
|  rhel-9-x86_64           /srv/pxeos/...     [Delete]  |
|  debian-12-amd64         /srv/pxeos/...     [Delete]  |
|                                                       |
|  -- or when empty --                                  |
|  No distros imported yet. Use the Import page to      |
|  add one.                                             |
+-------------------------------------------------------+
```

### Profiles (`/web/profiles`)

Create and manage provisioning profiles that define how machines are installed.

**Add Profile form** with fields:
- Profile Name, OS Family (dropdown of loaded plugins), Vendor, Version
- Architecture (x86_64, aarch64, amd64), Firmware (BIOS, UEFI), Install URL
- Packages (comma-separated), Post-install commands (textarea, one per line)

**Existing Profiles table** with columns:
- Name, OS, Vendor, Version, Arch, Firmware, Actions (Delete button)

The form uses htmx to submit and refresh the profile list without a full page reload. A success or error flash message is shown after submission.

```
+-------------------------------------------------------+
|  Provisioning Profiles                                |
|                                                       |
|  Add Profile                                          |
|  +------------+ +------------+ +--------+ +--------+ |
|  | Name       | | OS Family  | | Vendor | | Version| |
|  +------------+ +------------+ +--------+ +--------+ |
|  +--------+ +--------+ +---------------------------+ |
|  | Arch   | | Firmware| | Install URL              | |
|  +--------+ +--------+ +---------------------------+ |
|  +--------------------------------------------------+|
|  | Packages (comma-separated)                       | |
|  +--------------------------------------------------+|
|  +--------------------------------------------------+|
|  | Post-install commands (one per line)             | |
|  +--------------------------------------------------+|
|  [Add Profile]                                        |
|                                                       |
|  Existing Profiles                                    |
|  NAME     OS      VENDOR  VER  ARCH    FW    ACTIONS  |
|  websvr   fedora  fedora  42   x86_64  bios  [Delete] |
|  dbsvr    debian  debian  12   amd64   uefi  [Delete] |
+-------------------------------------------------------+
```

### Host Rules (`/web/hosts`)

Map machines to provisioning profiles using match criteria.

**Add Host Rule form** with fields:
- Profile, OS Family (dropdown), Vendor, Version
- MAC Address, Hostname Pattern (glob), Subnet (CIDR), Group
- Priority (numeric; lower value = higher priority)

**Existing Rules table** with columns:
- Priority, Profile, OS (formatted as `os_family/os_version [vendor]`), Match Criteria (displays all non-empty match fields as `key=value` code snippets)

When no match criteria are set, "default" is shown in muted text.

```
+-------------------------------------------------------+
|  Host Rules                                           |
|                                                       |
|  Add Host Rule                                        |
|  +----------+ +----------+ +--------+ +--------+     |
|  | Profile  | | OS Family| | Vendor | | Version|     |
|  +----------+ +----------+ +--------+ +--------+     |
|  +----------+ +-----------+ +--------+ +--------+    |
|  | MAC      | | Host Pat. | | Subnet | | Group  |    |
|  +----------+ +-----------+ +--------+ +--------+    |
|  +----------+                                         |
|  | Priority |                                         |
|  +----------+                                         |
|  [Add Host Rule]                                      |
|                                                       |
|  Existing Rules                                       |
|  PRI  PROFILE   OS             MATCH CRITERIA         |
|  10   websvr    fedora/42      mac=aa:bb:cc:dd:ee:f1  |
|  50   dbsvr     debian/12      subnet=10.0.5.0/24     |
|  100  minimal   ubuntu/24.04   group=lab              |
+-------------------------------------------------------+
```

### Cloud-Init (`/web/cloud-init`)

Generate cloud-init configuration files (user-data, meta-data, network-config) for VM or bare-metal provisioning.

**Form fields:**
- Instance Name, Hostname (defaults to name), User, Password (optional)
- SSH Authorized Keys (textarea, one key per line)
- Packages (comma-separated)
- Post-install commands (textarea, one per line)
- Network (DHCP or Static IP), IP Address, Gateway, DNS (comma-separated)
- Timezone, Locale

**Two action buttons:**
- "Generate" -- renders the cloud-init YAML output inline via htmx
- "Download ISO" -- generates and downloads a NoCloud config drive ISO file

**Output area** (shown after generation):
- user-data card (YAML `#cloud-config`)
- meta-data card (instance-id and hostname)
- network-config card (Netplan v2 format, shown only when relevant)

```
+-------------------------------------------------------+
|  Cloud-Init Config Generator                          |
|                                                       |
|  +----------+ +----------+ +--------+ +--------+     |
|  | Name     | | Hostname | | User   | | Password|    |
|  +----------+ +----------+ +--------+ +--------+     |
|  +--------------------------------------------------+|
|  | SSH Authorized Keys (one per line)               | |
|  +--------------------------------------------------+|
|  +--------------------------------------------------+|
|  | Packages (comma-separated)                       | |
|  +--------------------------------------------------+|
|  +--------------------------------------------------+|
|  | Post-install commands (one per line)             | |
|  +--------------------------------------------------+|
|  +--------+ +-------+ +--------+ +--------+          |
|  | Network| | IP    | | Gateway| | DNS    |          |
|  +--------+ +-------+ +--------+ +--------+          |
|  +----------+ +----------+                            |
|  | Timezone | | Locale   |                            |
|  +----------+ +----------+                            |
|  [Generate] [Download ISO]                            |
|                                                       |
|  -- output after generation --                        |
|  user-data                                            |
|  +--------------------------------------------------+|
|  | #cloud-config                                    | |
|  | hostname: myvm                                   | |
|  | users: ...                                       | |
|  +--------------------------------------------------+|
|  meta-data                                            |
|  +--------------------------------------------------+|
|  | instance-id: myvm                                | |
|  | local-hostname: myvm                             | |
|  +--------------------------------------------------+|
+-------------------------------------------------------+
```

### Import (`/web/import`)

Import OS distributions for PXE boot serving. Two methods are provided.

**Upload ISO form:**
- OS Family (dropdown), Vendor, Version, Architecture (dropdown)
- ISO File (file upload input, accepts `.iso`)
- "Upload & Import" button

**Fetch from URL form:**
- OS Family (dropdown), Vendor, Version, Architecture (dropdown)
- Kernel URL (required)
- Initrd URL (optional)
- "Fetch & Import" button

**Import Result** (shown after a successful or failed import):
- Success: shows kernel path, initrd path (if applicable), and repo path
- Failure: shows error message

Both forms use htmx for async submission with a spinner indicator.

```
+-------------------------------------------------------+
|  Import Distro                                        |
|                                                       |
|  Upload ISO                                           |
|  +----------+ +--------+ +--------+ +--------+       |
|  | OS Family| | Vendor | | Version| | Arch   |       |
|  +----------+ +--------+ +--------+ +--------+       |
|  +--------------------------------------------------+|
|  | [Choose ISO File]                                | |
|  +--------------------------------------------------+|
|  [Upload & Import]                                    |
|                                                       |
|  Fetch from URL                                       |
|  +----------+ +--------+ +--------+ +--------+       |
|  | OS Family| | Vendor | | Version| | Arch   |       |
|  +----------+ +--------+ +--------+ +--------+       |
|  +--------------------------------------------------+|
|  | Kernel URL                                       | |
|  +--------------------------------------------------+|
|  +--------------------------------------------------+|
|  | Initrd URL (optional)                            | |
|  +--------------------------------------------------+|
|  [Fetch & Import]                                     |
|                                                       |
|  -- result after import --                            |
|  Import Result                                        |
|  Kernel   /srv/pxeos/distros/fedora-42-x86_64/vmlinuz |
|  Initrd   /srv/pxeos/distros/fedora-42-x86_64/initrd |
|  Repo     /srv/pxeos/distros/fedora-42-x86_64        |
+-------------------------------------------------------+
```

## Capturing Screenshots

To capture actual browser screenshots of the web UI:

```bash
# Recommended: Playwright
pip install playwright && playwright install chromium
python scripts/capture_screenshots.py

# Alternative: shell script (auto-detects Playwright or Chrome)
./scripts/capture-screenshots.sh

# Custom server URL
python scripts/capture_screenshots.py --base-url https://pxeos:8443
```

Screenshots are saved to `docs/screenshots/`. See `scripts/capture_screenshots.py` for configuration options.

## Technology Stack

- **Backend:** FastAPI with Jinja2 templates (server-side rendering)
- **Interactivity:** htmx for dynamic form submission and partial page updates
- **Styling:** Custom CSS with dark theme (CSS custom properties)
- **Layout:** CSS Grid sidebar + main content area
- **Responsive:** Sidebar hidden on mobile (< 768px)
