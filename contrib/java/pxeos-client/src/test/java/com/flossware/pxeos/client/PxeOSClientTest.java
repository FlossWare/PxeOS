package com.flossware.pxeos.client;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Unit tests for the PxeOS Java client library.
 *
 * <p>These tests exercise URL construction, JSON serialization /
 * deserialization of all model classes, YAML descriptor parsing,
 * and basic error handling.  They do <b>not</b> require a running
 * PxeOS server.
 */
class PxeOSClientTest {

    private final ObjectMapper mapper = new ObjectMapper();

    // ----- URL construction ------------------------------------------------

    @Test
    void buildUrl_noTrailingSlash() {
        PxeOSClient client = new PxeOSClient("http://pxeos.local:8443");
        assertEquals("http://pxeos.local:8443/api/v1/health",
                client.buildUrl("/api/v1/health"));
    }

    @Test
    void buildUrl_trailingSlashStripped() {
        PxeOSClient client = new PxeOSClient("http://pxeos.local:8443/");
        assertEquals("http://pxeos.local:8443/api/v1/health",
                client.buildUrl("/api/v1/health"));
    }

    @Test
    void constructor_nullBaseUrl_throws() {
        assertThrows(IllegalArgumentException.class,
                () -> new PxeOSClient(null));
    }

    @Test
    void constructor_emptyBaseUrl_throws() {
        assertThrows(IllegalArgumentException.class,
                () -> new PxeOSClient(""));
    }

    // ----- HostRule JSON round-trip ----------------------------------------

    @Test
    void hostRule_jsonRoundTrip() throws Exception {
        HostRule rule = new HostRule("webserver", "fedora", "42",
                "Red Hat", "aa:bb:cc:dd:ee:ff", 10);
        rule.setArch("x86_64");

        String json = mapper.writeValueAsString(rule);
        assertTrue(json.contains("\"os_family\":\"fedora\""));
        assertTrue(json.contains("\"os_version\":\"42\""));
        assertTrue(json.contains("\"mac\":\"aa:bb:cc:dd:ee:ff\""));

        HostRule back = mapper.readValue(json, HostRule.class);
        assertEquals("webserver", back.getProfile());
        assertEquals("fedora", back.getOsFamily());
        assertEquals("42", back.getOsVersion());
        assertEquals("Red Hat", back.getVendor());
        assertEquals("aa:bb:cc:dd:ee:ff", back.getMac());
        assertEquals(10, back.getPriority());
        assertEquals("x86_64", back.getArch());
    }

    @Test
    void hostRule_nullFieldsOmitted() throws Exception {
        HostRule rule = new HostRule();
        rule.setProfile("base");
        rule.setOsFamily("debian");
        rule.setOsVersion("12");

        String json = mapper.writeValueAsString(rule);
        assertFalse(json.contains("\"mac_prefix\""));
        assertFalse(json.contains("\"subnet\""));
        assertFalse(json.contains("\"serial\""));
    }

    @Test
    void hostRule_deserializeFromApiResponse() throws Exception {
        String json = "{\"profile\":\"test\",\"os_family\":\"fedora\","
                + "\"os_version\":\"40\",\"vendor\":\"\","
                + "\"priority\":100,\"mac\":\"aa:bb:cc:dd:ee:ff\","
                + "\"unknown_field\":true}";
        HostRule rule = mapper.readValue(json, HostRule.class);
        assertEquals("test", rule.getProfile());
        assertEquals("aa:bb:cc:dd:ee:ff", rule.getMac());
    }

    // ----- ProvisionStatus JSON ------------------------------------------

    @Test
    void provisionStatus_deserialize() throws Exception {
        String json = "{\"mac\":\"aa:bb:cc:dd:ee:ff\","
                + "\"profile\":\"webserver\","
                + "\"os_family\":\"fedora\",\"os_version\":\"42\","
                + "\"state\":\"complete\","
                + "\"started_at\":1700000000.0,"
                + "\"completed_at\":1700003600.0,"
                + "\"history\":[{\"state\":\"registered\",\"timestamp\":1700000000.0}],"
                + "\"netboot_enabled\":false}";
        ProvisionStatus ps = mapper.readValue(json, ProvisionStatus.class);
        assertEquals("aa:bb:cc:dd:ee:ff", ps.getMac());
        assertEquals("complete", ps.getState());
        assertTrue(ps.isTerminal());
        assertFalse(ps.isNetbootEnabled());
        assertNotNull(ps.getHistory());
        assertEquals(1, ps.getHistory().size());
    }

    @Test
    void provisionStatus_isTerminal_failed() throws Exception {
        ProvisionStatus ps = new ProvisionStatus();
        ps.setState("failed");
        assertTrue(ps.isTerminal());
    }

    @Test
    void provisionStatus_isTerminal_installing() throws Exception {
        ProvisionStatus ps = new ProvisionStatus();
        ps.setState("installing");
        assertFalse(ps.isTerminal());
    }

    // ----- Profile JSON ---------------------------------------------------

    @Test
    void profile_jsonRoundTrip() throws Exception {
        Profile p = new Profile("webserver", "fedora", "42",
                "Red Hat", "x86_64");
        p.setFirmware("bios");

        String json = mapper.writeValueAsString(p);
        Profile back = mapper.readValue(json, Profile.class);
        assertEquals("webserver", back.getName());
        assertEquals("bios", back.getFirmware());
    }

    @Test
    void profile_deserializeList() throws Exception {
        String json = "[{\"name\":\"a\",\"os_family\":\"fedora\","
                + "\"os_version\":\"40\",\"arch\":\"x86_64\","
                + "\"firmware\":\"bios\"}]";
        List<Profile> profiles = mapper.readValue(json,
                mapper.getTypeFactory().constructCollectionType(
                        List.class, Profile.class));
        assertEquals(1, profiles.size());
        assertEquals("a", profiles.get(0).getName());
    }

    // ----- HealthStatus JSON -----------------------------------------------

    @Test
    void healthStatus_deserialize() throws Exception {
        String json = "{\"status\":\"ok\","
                + "\"plugins\":[\"fedora\",\"debian\",\"freebsd\"],"
                + "\"version\":\"1.0\","
                + "\"uptime_seconds\":123.4,"
                + "\"provision_count\":5}";
        HealthStatus hs = mapper.readValue(json, HealthStatus.class);
        assertEquals("ok", hs.getStatus());
        assertTrue(hs.isHealthy());
        assertEquals(3, hs.getPlugins().size());
        assertEquals("1.0", hs.getVersion());
    }

    @Test
    void healthStatus_notHealthy() {
        HealthStatus hs = new HealthStatus();
        hs.setStatus("degraded");
        assertFalse(hs.isHealthy());
    }

    // ----- YAML descriptor parsing -----------------------------------------

    @Test
    void parseDescriptor_valid(@TempDir Path tmp) throws Exception {
        Path yaml = tmp.resolve("deploy.yaml");
        Files.writeString(yaml, String.join("\n",
                "deployment:",
                "  name: webserver-cluster",
                "  nodes:",
                "    - hostname: web-01",
                "      mac: \"aa:bb:cc:dd:ee:f1\"",
                "      provision:",
                "        server: http://pxeos.local:8443",
                "        profile: webserver",
                "        os: fedora",
                "        version: \"42\"",
                "    - hostname: web-02",
                "      mac: \"aa:bb:cc:dd:ee:f2\"",
                "      provision:",
                "        server: http://pxeos.local:8443",
                "        profile: webserver",
                "        os: freebsd",
                "        version: \"14.2\""));

        Descriptor desc = PxeOSProvisioner.parseDescriptor(yaml);
        assertEquals("webserver-cluster", desc.getName());
        assertNotNull(desc.getNodes());
        assertEquals(2, desc.getNodes().size());

        Descriptor.Node n1 = desc.getNodes().get(0);
        assertEquals("web-01", n1.getHostname());
        assertEquals("aa:bb:cc:dd:ee:f1", n1.getMac());
        assertEquals("http://pxeos.local:8443", n1.getProvision().getServer());
        assertEquals("webserver", n1.getProvision().getProfile());
        assertEquals("fedora", n1.getProvision().getOs());
        assertEquals("42", n1.getProvision().getVersion());

        Descriptor.Node n2 = desc.getNodes().get(1);
        assertEquals("freebsd", n2.getProvision().getOs());
        assertEquals("14.2", n2.getProvision().getVersion());
    }

    @Test
    void parseDescriptor_missingDeploymentKey(@TempDir Path tmp) throws Exception {
        Path yaml = tmp.resolve("bad.yaml");
        Files.writeString(yaml, "nodes:\n  - hostname: x\n");

        IOException ex = assertThrows(IOException.class,
                () -> PxeOSProvisioner.parseDescriptor(yaml));
        assertTrue(ex.getMessage().contains("deployment"));
    }

    @Test
    void parseDescriptor_emptyNodes(@TempDir Path tmp) throws Exception {
        Path yaml = tmp.resolve("empty.yaml");
        Files.writeString(yaml, "deployment:\n  name: empty\n");

        Descriptor desc = PxeOSProvisioner.parseDescriptor(yaml);
        assertEquals("empty", desc.getName());
        assertTrue(desc.getNodes().isEmpty());
    }

    // ----- ProvisionResult -------------------------------------------------

    @Test
    void provisionResult_fullySuccessful() {
        List<ProvisionResult.NodeResult> ok = List.of(
                new ProvisionResult.NodeResult("web-01", "aa:bb:cc:dd:ee:f1", null));
        ProvisionResult r = new ProvisionResult("test", ok, List.of());
        assertTrue(r.isFullySuccessful());
        assertEquals(1, r.getTotalNodes());
    }

    @Test
    void provisionResult_withFailures() {
        List<ProvisionResult.NodeResult> ok = List.of(
                new ProvisionResult.NodeResult("web-01", "aa:bb:cc:dd:ee:f1", null));
        List<ProvisionResult.NodeResult> fail = List.of(
                new ProvisionResult.NodeResult("web-02", "aa:bb:cc:dd:ee:f2", "refused"));
        ProvisionResult r = new ProvisionResult("test", ok, fail);
        assertFalse(r.isFullySuccessful());
        assertEquals(2, r.getTotalNodes());
        assertTrue(r.getFailures().get(0).getError().contains("refused"));
    }

    @Test
    void provisionResult_emptyIsNotFullySuccessful() {
        ProvisionResult r = new ProvisionResult("empty", List.of(), List.of());
        assertFalse(r.isFullySuccessful());
    }

    // ----- Error handling --------------------------------------------------

    @Test
    void client_connectionRefused() {
        // Port 1 is almost certainly not listening.
        PxeOSClient client = new PxeOSClient("http://127.0.0.1:1");
        client.setConnectTimeoutMs(500);
        client.setReadTimeoutMs(500);
        assertThrows(IOException.class, client::checkHealth);
    }

    @Test
    void client_invalidHost() {
        PxeOSClient client = new PxeOSClient("http://host.invalid.test:9999");
        client.setConnectTimeoutMs(500);
        client.setReadTimeoutMs(500);
        assertThrows(IOException.class, client::checkHealth);
    }

    // ----- Descriptor model ------------------------------------------------

    @Test
    void descriptor_nodeResult_isSuccess() {
        ProvisionResult.NodeResult ok =
                new ProvisionResult.NodeResult("h", "m", null);
        assertTrue(ok.isSuccess());

        ProvisionResult.NodeResult bad =
                new ProvisionResult.NodeResult("h", "m", "err");
        assertFalse(bad.isSuccess());
    }
}
