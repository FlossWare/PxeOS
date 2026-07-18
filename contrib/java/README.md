# PxeOS Java Client

Java client library for the [PxeOS](https://github.com/FlossWare/PxeOS)
cross-OS PXE boot provisioning API.  Provides programmatic access to host
registration, provisioning status polling, and batch deployment via YAML
descriptors.

## Requirements

- Java 11 or later
- Maven 3.6+ (for building)

## Building

```bash
cd contrib/java/pxeos-client
mvn clean package
```

Run the tests:

```bash
mvn test
```

## Usage

### Basic client

```java
import com.flossware.pxeos.client.*;

// Without authentication
PxeOSClient client = new PxeOSClient("http://pxeos.local:8443");

// With an API key
PxeOSClient client = new PxeOSClient("http://pxeos.local:8443", apiKey);

// Check server health
HealthStatus health = client.checkHealth();
System.out.println("Status: " + health.getStatus());
System.out.println("Plugins: " + health.getPlugins());

// List available profiles
List<Profile> profiles = client.listProfiles();
```

### Register a host

```java
HostRule rule = new HostRule();
rule.setProfile("webserver");
rule.setOsFamily("fedora");
rule.setOsVersion("42");
rule.setMac("aa:bb:cc:dd:ee:ff");
rule.setPriority(10);

client.registerHost(rule);
```

### Poll provisioning status

```java
ProvisionStatus status = client.getStatus("aa:bb:cc:dd:ee:ff");
System.out.println("State: " + status.getState());

// Block until complete (with timeout)
ProvisionStatus final = client.waitForCompletion(
        "aa:bb:cc:dd:ee:ff", Duration.ofMinutes(30));
```

### Batch provisioning with YAML descriptors

```java
import com.flossware.pxeos.client.*;
import java.nio.file.Paths;

PxeOSProvisioner provisioner = new PxeOSProvisioner(apiKey);
ProvisionResult result = provisioner.provision(
        Paths.get("webserver-cluster.yaml"));

System.out.println("Deployed: " + result.getDeploymentName());
System.out.println("Successes: " + result.getSuccesses().size());
System.out.println("Failures: " + result.getFailures().size());
```

## YAML descriptor format

Deployment descriptors define a set of nodes to provision through PxeOS.
Each node specifies its MAC address, the target PxeOS server, the
provisioning profile, and the OS to install.

```yaml
deployment:
  name: webserver-cluster
  nodes:
    - hostname: web-01
      mac: "aa:bb:cc:dd:ee:f1"
      provision:
        server: http://pxeos.local:8443
        profile: webserver
        os: fedora
        version: "42"

    - hostname: web-02
      mac: "aa:bb:cc:dd:ee:f2"
      provision:
        server: http://pxeos.local:8443
        profile: webserver
        os: freebsd
        version: "14.2"
```

### Descriptor fields

| Field | Required | Description |
|-------|----------|-------------|
| `deployment.name` | yes | Human-readable deployment name |
| `nodes[].hostname` | yes | Target hostname |
| `nodes[].mac` | yes | MAC address (colon-separated) |
| `nodes[].provision.server` | yes | PxeOS server URL |
| `nodes[].provision.profile` | yes | Provisioning profile name |
| `nodes[].provision.os` | yes | OS family (fedora, debian, freebsd, etc.) |
| `nodes[].provision.version` | yes | OS version (must be quoted in YAML) |

See `examples/webserver-cluster.yaml` for a complete example.

## API endpoint mapping

| Java method | HTTP | PxeOS endpoint |
|-------------|------|----------------|
| `registerHost()` | POST | `/api/v1/hosts` |
| `getStatus()` | GET | `/api/v1/provision/{mac}/status` |
| `getBootScript()` | GET | `/api/v1/boot/{mac}` |
| `listProfiles()` | GET | `/api/v1/profiles` |
| `checkHealth()` | GET | `/api/v1/health` |

## End-to-end example: VM provisioning

1. Start the PxeOS server:
   ```bash
   pxeos serve --config /etc/pxeos/pxeos.toml
   ```

2. Create a YAML descriptor for your VMs (see `examples/`).

3. Run the provisioner:
   ```java
   PxeOSProvisioner provisioner = new PxeOSProvisioner();
   ProvisionResult result = provisioner.provision(
           Paths.get("my-cluster.yaml"));

   if (result.isFullySuccessful()) {
       System.out.println("All nodes registered for provisioning");
   } else {
       for (ProvisionResult.NodeResult f : result.getFailures()) {
           System.err.println(f.getHostname() + ": " + f.getError());
       }
   }
   ```

4. PXE-boot the target machines.  They will fetch their boot
   configuration from the PxeOS server and install the specified OS.

5. Monitor progress:
   ```java
   PxeOSClient client = new PxeOSClient("http://pxeos.local:8443");
   ProvisionStatus status = client.waitForCompletion(
           "aa:bb:cc:dd:ee:f1", Duration.ofMinutes(60));
   System.out.println("Final state: " + status.getState());
   ```

## License

GPL-3.0-or-later -- same as PxeOS.
