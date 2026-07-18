package com.flossware.pxeos.client;

import org.yaml.snakeyaml.Yaml;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeoutException;

/**
 * High-level provisioner that reads a YAML deployment descriptor
 * and registers each node with its target PxeOS server.
 *
 * <h3>Usage</h3>
 * <pre>
 * PxeOSProvisioner provisioner = new PxeOSProvisioner();
 * ProvisionResult result = provisioner.provision(
 *         Paths.get("webserver-cluster.yaml"));
 * </pre>
 */
public class PxeOSProvisioner {

    private final String apiKey;
    private Duration waitTimeout = Duration.ofMinutes(30);

    /**
     * Create a provisioner without authentication.
     */
    public PxeOSProvisioner() {
        this(null);
    }

    /**
     * Create a provisioner with an API key that will be passed
     * to each PxeOS server.
     */
    public PxeOSProvisioner(String apiKey) {
        this.apiKey = apiKey;
    }

    /**
     * Set the maximum time to wait for each node to finish
     * provisioning.  Default is 30 minutes.
     */
    public void setWaitTimeout(Duration timeout) {
        this.waitTimeout = timeout;
    }

    /**
     * Parse and provision all nodes described in a YAML descriptor.
     *
     * @param descriptorPath path to the YAML file
     * @return aggregated result
     * @throws IOException if the file cannot be read or a network
     *                     error occurs during registration
     */
    public ProvisionResult provision(Path descriptorPath) throws IOException {
        Descriptor descriptor = parseDescriptor(descriptorPath);
        return provision(descriptor);
    }

    /**
     * Provision all nodes in an already-parsed descriptor.
     *
     * @param descriptor the parsed deployment descriptor
     * @return aggregated result
     * @throws IOException on network errors
     */
    public ProvisionResult provision(Descriptor descriptor) throws IOException {
        if (descriptor == null || descriptor.getNodes() == null
                || descriptor.getNodes().isEmpty()) {
            return new ProvisionResult(
                    descriptor != null ? descriptor.getName() : null,
                    Collections.emptyList(), Collections.emptyList());
        }

        List<ProvisionResult.NodeResult> successes = new ArrayList<>();
        List<ProvisionResult.NodeResult> failures = new ArrayList<>();

        for (Descriptor.Node node : descriptor.getNodes()) {
            Descriptor.ProvisionConfig cfg = node.getProvision();
            if (cfg == null || cfg.getServer() == null) {
                failures.add(new ProvisionResult.NodeResult(
                        node.getHostname(), node.getMac(),
                        "missing provision config or server URL"));
                continue;
            }

            PxeOSClient client = (apiKey != null)
                    ? new PxeOSClient(cfg.getServer(), apiKey)
                    : new PxeOSClient(cfg.getServer());

            HostRule rule = new HostRule();
            rule.setMac(node.getMac());
            rule.setProfile(cfg.getProfile());
            rule.setOsFamily(cfg.getOs());
            rule.setOsVersion(cfg.getVersion());

            try {
                client.registerHost(rule);
                successes.add(new ProvisionResult.NodeResult(
                        node.getHostname(), node.getMac(), null));
            } catch (IOException e) {
                failures.add(new ProvisionResult.NodeResult(
                        node.getHostname(), node.getMac(), e.getMessage()));
            }
        }

        return new ProvisionResult(descriptor.getName(), successes, failures);
    }

    /**
     * Parse a YAML deployment descriptor file.
     *
     * @param path path to the YAML file
     * @return the parsed descriptor
     * @throws IOException if the file cannot be read or parsed
     */
    @SuppressWarnings("unchecked")
    public static Descriptor parseDescriptor(Path path) throws IOException {
        Yaml yaml = new Yaml();
        Map<String, Object> root;
        try (InputStream in = Files.newInputStream(path)) {
            root = yaml.load(in);
        }

        if (root == null || !root.containsKey("deployment")) {
            throw new IOException(
                    "Invalid descriptor: missing top-level 'deployment' key");
        }

        Map<String, Object> deployment = (Map<String, Object>) root.get("deployment");
        Descriptor descriptor = new Descriptor();
        descriptor.setName((String) deployment.get("name"));

        List<Map<String, Object>> rawNodes =
                (List<Map<String, Object>>) deployment.get("nodes");

        if (rawNodes == null) {
            descriptor.setNodes(Collections.emptyList());
            return descriptor;
        }

        List<Descriptor.Node> nodes = new ArrayList<>();
        for (Map<String, Object> rawNode : rawNodes) {
            Descriptor.Node node = new Descriptor.Node();
            node.setHostname((String) rawNode.get("hostname"));
            node.setMac((String) rawNode.get("mac"));

            Map<String, Object> rawProv =
                    (Map<String, Object>) rawNode.get("provision");
            if (rawProv != null) {
                Descriptor.ProvisionConfig cfg = new Descriptor.ProvisionConfig();
                cfg.setServer((String) rawProv.get("server"));
                cfg.setProfile((String) rawProv.get("profile"));
                cfg.setOs((String) rawProv.get("os"));
                Object ver = rawProv.get("version");
                cfg.setVersion(ver != null ? ver.toString() : null);
                node.setProvision(cfg);
            }

            nodes.add(node);
        }
        descriptor.setNodes(nodes);
        return descriptor;
    }
}
