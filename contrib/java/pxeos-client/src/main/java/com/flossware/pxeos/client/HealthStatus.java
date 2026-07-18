package com.flossware.pxeos.client;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;

/**
 * Server health information.  Mirrors the PxeOS API
 * HealthResponse schema.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
@JsonInclude(JsonInclude.Include.NON_NULL)
public class HealthStatus {

    @JsonProperty("status")
    private String status;

    @JsonProperty("plugins")
    private List<String> plugins;

    @JsonProperty("version")
    private String version;

    @JsonProperty("uptime_seconds")
    private Double uptimeSeconds;

    @JsonProperty("provision_count")
    private Integer provisionCount;

    @JsonProperty("data_dir_free_bytes")
    private Long dataDirFreeBytes;

    public HealthStatus() {}

    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }

    public List<String> getPlugins() { return plugins; }
    public void setPlugins(List<String> plugins) { this.plugins = plugins; }

    public String getVersion() { return version; }
    public void setVersion(String version) { this.version = version; }

    public Double getUptimeSeconds() { return uptimeSeconds; }
    public void setUptimeSeconds(Double uptimeSeconds) { this.uptimeSeconds = uptimeSeconds; }

    public Integer getProvisionCount() { return provisionCount; }
    public void setProvisionCount(Integer provisionCount) { this.provisionCount = provisionCount; }

    public Long getDataDirFreeBytes() { return dataDirFreeBytes; }
    public void setDataDirFreeBytes(Long dataDirFreeBytes) { this.dataDirFreeBytes = dataDirFreeBytes; }

    /**
     * Return {@code true} when the server reports itself healthy.
     */
    public boolean isHealthy() {
        return "ok".equals(status);
    }
}
