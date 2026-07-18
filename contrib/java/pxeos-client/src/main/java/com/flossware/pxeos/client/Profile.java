package com.flossware.pxeos.client;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * A provisioning profile.  Mirrors the PxeOS API ProfileResponse
 * schema.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
@JsonInclude(JsonInclude.Include.NON_NULL)
public class Profile {

    @JsonProperty("name")
    private String name;

    @JsonProperty("os_family")
    private String osFamily;

    @JsonProperty("os_version")
    private String osVersion;

    @JsonProperty("vendor")
    private String vendor;

    @JsonProperty("arch")
    private String arch;

    @JsonProperty("firmware")
    private String firmware;

    public Profile() {}

    public Profile(String name, String osFamily, String osVersion,
                   String vendor, String arch) {
        this.name = name;
        this.osFamily = osFamily;
        this.osVersion = osVersion;
        this.vendor = vendor;
        this.arch = arch;
    }

    public String getName() { return name; }
    public void setName(String name) { this.name = name; }

    public String getOsFamily() { return osFamily; }
    public void setOsFamily(String osFamily) { this.osFamily = osFamily; }

    public String getOsVersion() { return osVersion; }
    public void setOsVersion(String osVersion) { this.osVersion = osVersion; }

    public String getVendor() { return vendor; }
    public void setVendor(String vendor) { this.vendor = vendor; }

    public String getArch() { return arch; }
    public void setArch(String arch) { this.arch = arch; }

    public String getFirmware() { return firmware; }
    public void setFirmware(String firmware) { this.firmware = firmware; }
}
