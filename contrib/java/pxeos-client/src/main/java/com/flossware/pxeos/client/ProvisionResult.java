package com.flossware.pxeos.client;

import java.util.Collections;
import java.util.List;

/**
 * Aggregated result of a batch provisioning operation from a YAML
 * deployment descriptor.
 */
public class ProvisionResult {

    private final String deploymentName;
    private final List<NodeResult> successes;
    private final List<NodeResult> failures;

    public ProvisionResult(String deploymentName,
                           List<NodeResult> successes,
                           List<NodeResult> failures) {
        this.deploymentName = deploymentName;
        this.successes = successes != null
                ? Collections.unmodifiableList(successes)
                : Collections.emptyList();
        this.failures = failures != null
                ? Collections.unmodifiableList(failures)
                : Collections.emptyList();
    }

    public String getDeploymentName() { return deploymentName; }
    public List<NodeResult> getSuccesses() { return successes; }
    public List<NodeResult> getFailures() { return failures; }

    /**
     * Return the total number of nodes processed (successes + failures).
     */
    public int getTotalNodes() {
        return successes.size() + failures.size();
    }

    /**
     * Return {@code true} if every node was registered successfully.
     */
    public boolean isFullySuccessful() {
        return failures.isEmpty() && !successes.isEmpty();
    }

    /**
     * Per-node outcome of a provisioning attempt.
     */
    public static class NodeResult {
        private final String hostname;
        private final String mac;
        private final String error;

        public NodeResult(String hostname, String mac, String error) {
            this.hostname = hostname;
            this.mac = mac;
            this.error = error;
        }

        public String getHostname() { return hostname; }
        public String getMac() { return mac; }
        public String getError() { return error; }

        /**
         * Return {@code true} when this node was registered
         * without error.
         */
        public boolean isSuccess() { return error == null; }
    }
}
