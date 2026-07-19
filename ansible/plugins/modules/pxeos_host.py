#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, FlossWare
# GNU General Public License v3.0+
# (see https://www.gnu.org/licenses/gpl-3.0.txt)

"""Ansible module to register/manage PxeOS hosts."""

from __future__ import annotations

DOCUMENTATION = r"""
---
module: pxeos_host
short_description: Manage PxeOS host registrations
version_added: "1.0.0"
description:
  - Create, update, or delete named host entries on a PxeOS server
    via the REST API.  Each host binds a MAC address to a profile
    or distro for PXE provisioning.
options:
  name:
    description:
      - Unique name for the host entry.
    required: true
    type: str
  state:
    description:
      - Whether the host should be present or absent.
    choices: [present, absent]
    default: present
    type: str
  mac:
    description:
      - MAC address of the host (e.g. aa:bb:cc:dd:ee:ff).
    type: str
  profile:
    description:
      - Provisioning profile name to bind the host to.
    type: str
    default: ""
  distro:
    description:
      - Named distro to bind the host to (alternative to profile).
    type: str
    default: ""
  hostname:
    description:
      - Hostname to assign during provisioning.
    type: str
    default: ""
  gateway:
    description:
      - Default gateway for the host.
    type: str
    default: ""
  nameservers:
    description:
      - List of DNS nameservers.
    type: list
    elements: str
    default: []
  ip_address:
    description:
      - Static IP address for the host.
    type: str
    default: ""
  netmask:
    description:
      - Network mask for the static IP.
    type: str
    default: ""
  comment:
    description:
      - Free-form comment.
    type: str
    default: ""
  extra:
    description:
      - Arbitrary key-value metadata.
    type: dict
    default: {}
  server_url:
    description:
      - Base URL of the PxeOS server.
    required: true
    type: str
  api_key:
    description:
      - Bearer API key for authentication. Can also be set via
        the C(PXEOS_API_KEY) environment variable.
    type: str
  validate_certs:
    description:
      - Whether to validate TLS certificates.
    type: bool
    default: true
  timeout:
    description:
      - HTTP request timeout in seconds.
    type: int
    default: 30
author:
  - FlossWare
"""

EXAMPLES = r"""
- name: Register a host for PXE provisioning
  flossware.pxeos.pxeos_host:
    name: web-server-01
    mac: "aa:bb:cc:dd:ee:01"
    profile: fedora42
    hostname: web-server-01.example.com
    ip_address: 192.168.1.100
    netmask: 255.255.255.0
    gateway: 192.168.1.1
    nameservers:
      - 8.8.8.8
      - 8.8.4.4
    server_url: https://pxe.example.com:8443
    api_key: pxeos_xxxx
    state: present

- name: Remove a host
  flossware.pxeos.pxeos_host:
    name: web-server-01
    server_url: https://pxe.example.com:8443
    api_key: pxeos_xxxx
    state: absent
"""

RETURN = r"""
host:
  description: The host object as returned by the PxeOS API.
  returned: when state=present
  type: dict
  sample:
    name: web-server-01
    mac: "aa:bb:cc:dd:ee:01"
    profile: fedora42
    hostname: web-server-01.example.com
"""

import os

from ansible.module_utils.basic import AnsibleModule

from ansible_collections.flossware.pxeos.plugins.module_utils.pxeos_api import (
    PxeOSAPIError,
    api_request,
)


def _host_url(server_url: str, name: str = "") -> str:
    base = server_url.rstrip("/")
    if name:
        return f"{base}/api/v1/named/hosts/{name}"
    return f"{base}/api/v1/named/hosts"


def _get_host(server_url, name, api_key, validate_certs, timeout):
    """Fetch a named host; returns None if not found."""
    url = _host_url(server_url, name)
    try:
        _status, body = api_request(
            url, "GET", api_key=api_key,
            validate_certs=validate_certs, timeout=timeout,
        )
        return body
    except PxeOSAPIError as exc:
        if exc.status == 404:
            return None
        raise


def _create_host(server_url, payload, api_key, validate_certs, timeout):
    url = _host_url(server_url)
    _status, body = api_request(
        url, "POST", data=payload, api_key=api_key,
        validate_certs=validate_certs, timeout=timeout,
    )
    return body


def _update_host(server_url, name, updates, api_key, validate_certs, timeout):
    url = _host_url(server_url, name)
    _status, body = api_request(
        url, "PUT", data=updates, api_key=api_key,
        validate_certs=validate_certs, timeout=timeout,
    )
    return body


def _delete_host(server_url, name, api_key, validate_certs, timeout):
    url = _host_url(server_url, name)
    api_request(
        url, "DELETE", api_key=api_key,
        validate_certs=validate_certs, timeout=timeout,
    )


def _build_payload(params):
    """Build a host payload from module params."""
    return {
        "name": params["name"],
        "mac": params["mac"],
        "profile": params.get("profile", ""),
        "distro": params.get("distro", ""),
        "hostname": params.get("hostname", ""),
        "gateway": params.get("gateway", ""),
        "nameservers": params.get("nameservers", []),
        "ip_address": params.get("ip_address", ""),
        "netmask": params.get("netmask", ""),
        "comment": params.get("comment", ""),
        "extra": params.get("extra", {}),
    }


def _needs_update(existing, desired):
    """Return dict of fields that differ between existing and desired."""
    changes = {}
    for key, val in desired.items():
        if key == "name":
            continue
        if existing.get(key) != val:
            changes[key] = val
    return changes


def run_module():
    module_args = dict(
        name=dict(type="str", required=True),
        state=dict(type="str", default="present", choices=["present", "absent"]),
        mac=dict(type="str"),
        profile=dict(type="str", default=""),
        distro=dict(type="str", default=""),
        hostname=dict(type="str", default=""),
        gateway=dict(type="str", default=""),
        nameservers=dict(type="list", elements="str", default=[]),
        ip_address=dict(type="str", default=""),
        netmask=dict(type="str", default=""),
        comment=dict(type="str", default=""),
        extra=dict(type="dict", default={}),
        server_url=dict(type="str", required=True),
        api_key=dict(type="str", no_log=True),
        validate_certs=dict(type="bool", default=True),
        timeout=dict(type="int", default=30),
    )

    module = AnsibleModule(
        argument_spec=module_args,
        required_if=[
            ("state", "present", ("mac",)),
        ],
        supports_check_mode=True,
    )

    params = module.params
    api_key = params["api_key"] or os.environ.get("PXEOS_API_KEY", "")
    server_url = params["server_url"]
    validate_certs = params["validate_certs"]
    timeout = params["timeout"]
    name = params["name"]
    state = params["state"]

    try:
        existing = _get_host(
            server_url, name, api_key, validate_certs, timeout,
        )
    except PxeOSAPIError as exc:
        module.fail_json(msg=f"Failed to query host: {exc}")
        return

    changed = False
    result_host = existing

    if state == "absent":
        if existing is not None:
            changed = True
            if not module.check_mode:
                try:
                    _delete_host(
                        server_url, name, api_key,
                        validate_certs, timeout,
                    )
                except PxeOSAPIError as exc:
                    module.fail_json(msg=f"Failed to delete host: {exc}")
                    return
            result_host = None
        module.exit_json(changed=changed, host=result_host)
        return

    # state == "present"
    desired = _build_payload(params)

    if existing is None:
        changed = True
        if not module.check_mode:
            try:
                result_host = _create_host(
                    server_url, desired, api_key,
                    validate_certs, timeout,
                )
            except PxeOSAPIError as exc:
                module.fail_json(msg=f"Failed to create host: {exc}")
                return
        else:
            result_host = desired
    else:
        updates = _needs_update(existing, desired)
        if updates:
            changed = True
            if not module.check_mode:
                try:
                    result_host = _update_host(
                        server_url, name, updates, api_key,
                        validate_certs, timeout,
                    )
                except PxeOSAPIError as exc:
                    module.fail_json(msg=f"Failed to update host: {exc}")
                    return
            else:
                result_host = {**existing, **updates}

    module.exit_json(changed=changed, host=result_host)


def main():
    run_module()


if __name__ == "__main__":
    main()
