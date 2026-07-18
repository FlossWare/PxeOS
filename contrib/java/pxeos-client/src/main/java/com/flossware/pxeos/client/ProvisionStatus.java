package com.flossware.pxeos.client;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;
import java.util.Map;

/**
 * Provisioning status for a host.  Mirrors the PxeOS API
 * ProvisionStatusResponse schema.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
@JsonInclude(JsonInclude.Include.NON_NULL)
public class ProvisionStatus {

    @JsonProperty("mac")
    private String mac;

    @JsonProperty("profile")
    private String profile;

    @JsonProperty("os_family")
    private String osFamily;

    @JsonProperty("os_version")
    private String osVersion;

    @JsonProperty("state")
    private String state;

    @JsonProperty("started_at")
    private Double startedAt;

    @JsonProperty("updated_at")
    private Double updatedAt;

    @JsonProperty("completed_at")
    private Double completedAt;

    @JsonProperty("error_message")
    private String errorMessage;

    @JsonProperty("history")
    private List<Map<String, Object>> history;

    @JsonProperty("netboot_enabled")
    private boolean netbootEnabled = true;

    public ProvisionStatus() {}

    public String getMac() { return mac; }
    public void setMac(String mac) { this.mac = mac; }

    public String getProfile() { return profile; }
    public void setProfile(String profile) { this.profile = profile; }

    public String getOsFamily() { return osFamily; }
    public void setOsFamily(String osFamily) { this.osFamily = osFamily; }

    public String getOsVersion() { return osVersion; }
    public void setOsVersion(String osVersion) { this.osVersion = osVersion; }

    public String getState() { return state; }
    public void setState(String state) { this.state = state; }

    public Double getStartedAt() { return startedAt; }
    public void setStartedAt(Double startedAt) { this.startedAt = startedAt; }

    public Double getUpdatedAt() { return updatedAt; }
    public void setUpdatedAt(Double updatedAt) { this.updatedAt = updatedAt; }

    public Double getCompletedAt() { return completedAt; }
    public void setCompletedAt(Double completedAt) { this.completedAt = completedAt; }

    public String getErrorMessage() { return errorMessage; }
    public void setErrorMessage(String errorMessage) { this.errorMessage = errorMessage; }

    public List<Map<String, Object>> getHistory() { return history; }
    public void setHistory(List<Map<String, Object>> history) { this.history = history; }

    public boolean isNetbootEnabled() { return netbootEnabled; }
    public void setNetbootEnabled(boolean netbootEnabled) { this.netbootEnabled = netbootEnabled; }

    /**
     * Return {@code true} if the provision has reached a terminal
     * state ({@code "complete"} or {@code "failed"}).
     */
    public boolean isTerminal() {
        return "complete".equals(state) || "failed".equals(state);
    }
}
