package com.flossware.pxeos.client;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * A host rule that maps a machine (by MAC, subnet, etc.) to a
 * provisioning profile.  Mirrors the PxeOS API HostRuleRequest
 * schema.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
@JsonInclude(JsonInclude.Include.NON_NULL)
public class HostRule {

    @JsonProperty("profile")
    private String profile;

    @JsonProperty("os_family")
    private String osFamily;

    @JsonProperty("os_version")
    private String osVersion;

    @JsonProperty("vendor")
    private String vendor;

    @JsonProperty("mac")
    private String mac;

    @JsonProperty("priority")
    private int priority = 100;

    @JsonProperty("mac_prefix")
    private String macPrefix;

    @JsonProperty("hostname_pattern")
    private String hostnamePattern;

    @JsonProperty("subnet")
    private String subnet;

    @JsonProperty("serial")
    private String serial;

    @JsonProperty("group")
    private String group;

    @JsonProperty("arch")
    private String arch;

    public HostRule() {}

    public HostRule(String profile, String osFamily, String osVersion,
                    String vendor, String mac, int priority) {
        this.profile = profile;
        this.osFamily = osFamily;
        this.osVersion = osVersion;
        this.vendor = vendor;
        this.mac = mac;
        this.priority = priority;
    }

    public String getProfile() { return profile; }
    public void setProfile(String profile) { this.profile = profile; }

    public String getOsFamily() { return osFamily; }
    public void setOsFamily(String osFamily) { this.osFamily = osFamily; }

    public String getOsVersion() { return osVersion; }
    public void setOsVersion(String osVersion) { this.osVersion = osVersion; }

    public String getVendor() { return vendor; }
    public void setVendor(String vendor) { this.vendor = vendor; }

    public String getMac() { return mac; }
    public void setMac(String mac) { this.mac = mac; }

    public int getPriority() { return priority; }
    public void setPriority(int priority) { this.priority = priority; }

    public String getMacPrefix() { return macPrefix; }
    public void setMacPrefix(String macPrefix) { this.macPrefix = macPrefix; }

    public String getHostnamePattern() { return hostnamePattern; }
    public void setHostnamePattern(String hostnamePattern) { this.hostnamePattern = hostnamePattern; }

    public String getSubnet() { return subnet; }
    public void setSubnet(String subnet) { this.subnet = subnet; }

    public String getSerial() { return serial; }
    public void setSerial(String serial) { this.serial = serial; }

    public String getGroup() { return group; }
    public void setGroup(String group) { this.group = group; }

    public String getArch() { return arch; }
    public void setArch(String arch) { this.arch = arch; }
}
