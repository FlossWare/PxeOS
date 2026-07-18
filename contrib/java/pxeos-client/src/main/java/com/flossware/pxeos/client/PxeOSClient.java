package com.flossware.pxeos.client;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.List;
import java.util.concurrent.TimeoutException;

/**
 * HTTP client for the PxeOS REST API.
 *
 * <p>Uses {@code java.net.HttpURLConnection} so no external HTTP
 * library is required beyond the JDK (Java 11+).
 *
 * <h3>Usage</h3>
 * <pre>
 * PxeOSClient client = new PxeOSClient("http://pxeos.local:8443");
 * HealthStatus health = client.checkHealth();
 * </pre>
 *
 * <p>When the server has authentication enabled, pass an API key:
 * <pre>
 * PxeOSClient client = new PxeOSClient("http://pxeos.local:8443", apiKey);
 * </pre>
 */
public class PxeOSClient {

    private static final int DEFAULT_CONNECT_TIMEOUT_MS = 10_000;
    private static final int DEFAULT_READ_TIMEOUT_MS = 30_000;

    private final String baseUrl;
    private final String apiKey;
    private final ObjectMapper mapper;
    private int connectTimeoutMs = DEFAULT_CONNECT_TIMEOUT_MS;
    private int readTimeoutMs = DEFAULT_READ_TIMEOUT_MS;

    /**
     * Create a client without authentication.
     *
     * @param baseUrl PxeOS server URL, e.g. {@code "http://pxeos.local:8443"}
     */
    public PxeOSClient(String baseUrl) {
        this(baseUrl, null);
    }

    /**
     * Create a client with Bearer-token authentication.
     *
     * @param baseUrl PxeOS server URL
     * @param apiKey  Bearer token (may be {@code null} for unauthenticated access)
     */
    public PxeOSClient(String baseUrl, String apiKey) {
        if (baseUrl == null || baseUrl.isEmpty()) {
            throw new IllegalArgumentException("baseUrl must not be null or empty");
        }
        // Strip trailing slash for consistent URL construction.
        this.baseUrl = baseUrl.endsWith("/")
                ? baseUrl.substring(0, baseUrl.length() - 1)
                : baseUrl;
        this.apiKey = apiKey;
        this.mapper = new ObjectMapper();
    }

    // ----- Configuration ---------------------------------------------------

    /**
     * Set the TCP connect timeout in milliseconds.
     */
    public void setConnectTimeoutMs(int ms) {
        this.connectTimeoutMs = ms;
    }

    /**
     * Set the socket read timeout in milliseconds.
     */
    public void setReadTimeoutMs(int ms) {
        this.readTimeoutMs = ms;
    }

    // ----- Public API methods ----------------------------------------------

    /**
     * Register a host rule.  Requires ADMIN role when auth is enabled.
     *
     * @param rule the host rule to register
     * @throws IOException on network or server errors
     */
    public void registerHost(HostRule rule) throws IOException {
        byte[] body = mapper.writeValueAsBytes(rule);
        doRequest("POST", "/api/v1/hosts", body);
    }

    /**
     * Get the provisioning status for a MAC address.
     *
     * @param mac colon-separated MAC (e.g. {@code "aa:bb:cc:dd:ee:ff"})
     * @return the current provisioning status
     * @throws IOException on network or server errors
     */
    public ProvisionStatus getStatus(String mac) throws IOException {
        byte[] resp = doRequest("GET", "/api/v1/provision/" + mac + "/status", null);
        return mapper.readValue(resp, ProvisionStatus.class);
    }

    /**
     * Fetch the iPXE boot script for a MAC address.
     *
     * @param mac colon-separated MAC
     * @return the boot script as plain text
     * @throws IOException on network or server errors
     */
    public String getBootScript(String mac) throws IOException {
        byte[] resp = doRequest("GET", "/api/v1/boot/" + mac, null);
        return new String(resp, StandardCharsets.UTF_8);
    }

    /**
     * List all available provisioning profiles.
     *
     * @return list of profiles
     * @throws IOException on network or server errors
     */
    public List<Profile> listProfiles() throws IOException {
        byte[] resp = doRequest("GET", "/api/v1/profiles", null);
        return mapper.readValue(resp, new TypeReference<List<Profile>>() {});
    }

    /**
     * Check server health.
     *
     * @return health status
     * @throws IOException on network or server errors
     */
    public HealthStatus checkHealth() throws IOException {
        byte[] resp = doRequest("GET", "/api/v1/health", null);
        return mapper.readValue(resp, HealthStatus.class);
    }

    /**
     * Poll the provisioning status until it reaches a terminal state
     * ({@code complete} or {@code failed}), or until the timeout
     * expires.
     *
     * @param mac     colon-separated MAC
     * @param timeout maximum time to wait
     * @return the final provisioning status
     * @throws IOException      on network or server errors
     * @throws TimeoutException if the timeout is exceeded
     */
    public ProvisionStatus waitForCompletion(String mac, Duration timeout)
            throws IOException, TimeoutException {
        long deadline = System.currentTimeMillis() + timeout.toMillis();
        long pollIntervalMs = 2_000;

        while (System.currentTimeMillis() < deadline) {
            ProvisionStatus status = getStatus(mac);
            if (status.isTerminal()) {
                return status;
            }
            try {
                Thread.sleep(Math.min(pollIntervalMs, deadline - System.currentTimeMillis()));
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                throw new IOException("Interrupted while waiting for provisioning", e);
            }
            // Simple back-off: increase interval up to 10 s.
            pollIntervalMs = Math.min(pollIntervalMs + 1_000, 10_000);
        }
        throw new TimeoutException(
                "Provisioning for " + mac + " did not complete within " + timeout);
    }

    // ----- URL construction (package-private for testing) ------------------

    String buildUrl(String path) {
        return baseUrl + path;
    }

    // ----- Internal HTTP plumbing ------------------------------------------

    private byte[] doRequest(String method, String path, byte[] body) throws IOException {
        URL url = new URL(buildUrl(path));
        HttpURLConnection conn = (HttpURLConnection) url.openConnection();
        try {
            conn.setRequestMethod(method);
            conn.setConnectTimeout(connectTimeoutMs);
            conn.setReadTimeout(readTimeoutMs);
            conn.setRequestProperty("Accept", "application/json");

            if (apiKey != null && !apiKey.isEmpty()) {
                conn.setRequestProperty("Authorization", "Bearer " + apiKey);
            }

            if (body != null) {
                conn.setDoOutput(true);
                conn.setRequestProperty("Content-Type", "application/json");
                try (OutputStream out = conn.getOutputStream()) {
                    out.write(body);
                }
            }

            int code = conn.getResponseCode();
            if (code >= 400) {
                String errorBody = readStream(conn.getErrorStream());
                throw new IOException(
                        "HTTP " + code + " from " + method + " " + path + ": " + errorBody);
            }

            return readStream(conn.getInputStream());
        } finally {
            conn.disconnect();
        }
    }

    private static byte[] readStream(InputStream is) throws IOException {
        if (is == null) {
            return new byte[0];
        }
        try (InputStream in = is) {
            return in.readAllBytes();
        }
    }
}
