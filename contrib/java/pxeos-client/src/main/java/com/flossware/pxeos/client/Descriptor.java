package com.flossware.pxeos.client;

import java.util.List;

/**
 * YAML deployment descriptor for batch provisioning of hosts
 * through PxeOS.
 *
 * <p>Expected YAML structure:
 * <pre>
 * deployment:
 *   name: webserver-cluster
 *   nodes:
 *     - hostname: web-01
 *       mac: "aa:bb:cc:dd:ee:f1"
 *       provision:
 *         server: http://pxeos.local:8443
 *         profile: webserver
 *         os: fedora
 *         version: "42"
 * </pre>
 */
public class Descriptor {

    private String name;
    private List<Node> nodes;

    public Descriptor() {}

    public String getName() { return name; }
    public void setName(String name) { this.name = name; }

    public List<Node> getNodes() { return nodes; }
    public void setNodes(List<Node> nodes) { this.nodes = nodes; }

    /**
     * A single node in the deployment descriptor.
     */
    public static class Node {
        private String hostname;
        private String mac;
        private ProvisionConfig provision;

        public Node() {}

        public String getHostname() { return hostname; }
        public void setHostname(String hostname) { this.hostname = hostname; }

        public String getMac() { return mac; }
        public void setMac(String mac) { this.mac = mac; }

        public ProvisionConfig getProvision() { return provision; }
        public void setProvision(ProvisionConfig provision) { this.provision = provision; }
    }

    /**
     * Per-node provisioning configuration referencing a PxeOS
     * server and profile.
     */
    public static class ProvisionConfig {
        private String server;
        private String profile;
        private String os;
        private String version;

        public ProvisionConfig() {}

        public String getServer() { return server; }
        public void setServer(String server) { this.server = server; }

        public String getProfile() { return profile; }
        public void setProfile(String profile) { this.profile = profile; }

        public String getOs() { return os; }
        public void setOs(String os) { this.os = os; }

        public String getVersion() { return version; }
        public void setVersion(String version) { this.version = version; }
    }
}
