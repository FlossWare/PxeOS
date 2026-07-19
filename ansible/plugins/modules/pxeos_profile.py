#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, FlossWare
# GNU General Public License v3.0+
# (see https://www.gnu.org/licenses/gpl-3.0.txt)

"""Ansible module to manage PxeOS provisioning profiles (named distros)."""

from __future__ import annotations

DOCUMENTATION = r"""
---
module: pxeos_profile
short_description: Manage PxeOS provisioning profiles
version_added: "1.0.0"
description:
  - Create, update, or delete provisioning profiles (named distros)
    on a PxeOS server via the REST API.
options:
  name:
    description:
      - Unique name for the provisioning profile.
    required: true
    type: str
  state:
    description:
      - Whether the profile should be present or absent.
    choices: [present, absent]
    default: present
    type: str
  os_family:
    description:
      - OS family (e.g. fedora, debian, ubuntu, suse, windows).
    type: str
  vendor:
    description:
      - OS vendor string.
    type: str
    default: ""
  version:
    description:
      - OS version string (e.g. "42", "12.0", "24.04").
    type: str
  arch:
    description:
      - CPU architecture.
    type: str
    default: x86_64
  kernel_path:
    description:
      - Path or URL to the kernel image.
    type: str
    default: ""
  initrd_path:
    description:
      - Path or URL to the initrd image.
    type: str
    default: ""
  install_url:
    description:
      - Base URL for the installation tree.
    type: str
    default: ""
  comment:
    description:
      - Free-form comment for the profile.
    type: str
    default: ""
  server_url:
    description:
      - Base URL of the PxeOS server (e.g. https://pxe.example.com:8443).
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
- name: Create a Fedora 42 profile
  flossware.pxeos.pxeos_profile:
    name: fedora42
    os_family: fedora
    vendor: Fedora Project
    version: "42"
    arch: x86_64
    kernel_path: /distros/fedora/42/vmlinuz
    initrd_path: /distros/fedora/42/initrd.img
    install_url: http://mirror.example.com/fedora/42/x86_64/os
    server_url: https://pxe.example.com:8443
    api_key: pxeos_xxxx
    state: present

- name: Remove a profile
  flossware.pxeos.pxeos_profile:
    name: fedora42
    server_url: https://pxe.example.com:8443
    api_key: pxeos_xxxx
    state: absent
"""

RETURN = r"""
profile:
  description: The profile object as returned by the PxeOS API.
  returned: when state=present
  type: dict
  sample:
    name: fedora42
    os_family: fedora
    vendor: "Fedora Project"
    version: "42"
    arch: x86_64
"""

import os

from ansible.module_utils.basic import AnsibleModule

# Import path is resolved by Ansible collection loader at runtime.
from ansible_collections.flossware.pxeos.plugins.module_utils.pxeos_api import (
    PxeOSAPIError,
    api_request,
)


def _distro_url(server_url: str, name: str = "") -> str:
    base = server_url.rstrip("/")
    if name:
        return f"{base}/api/v1/named/distros/{name}"
    return f"{base}/api/v1/named/distros"


def _get_distro(server_url, name, api_key, validate_certs, timeout):
    """Fetch a named distro by name; returns None if not found."""
    url = _distro_url(server_url, name)
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


def _create_distro(server_url, payload, api_key, validate_certs, timeout):
    url = _distro_url(server_url)
    _status, body = api_request(
        url, "POST", data=payload, api_key=api_key,
        validate_certs=validate_certs, timeout=timeout,
    )
    return body


def _update_distro(server_url, name, updates, api_key, validate_certs, timeout):
    url = _distro_url(server_url, name)
    _status, body = api_request(
        url, "PUT", data=updates, api_key=api_key,
        validate_certs=validate_certs, timeout=timeout,
    )
    return body


def _delete_distro(server_url, name, api_key, validate_certs, timeout):
    url = _distro_url(server_url, name)
    api_request(
        url, "DELETE", api_key=api_key,
        validate_certs=validate_certs, timeout=timeout,
    )


def _build_payload(params):
    """Build a distro payload from module params."""
    return {
        "name": params["name"],
        "os_family": params["os_family"],
        "vendor": params.get("vendor", ""),
        "version": params["version"],
        "arch": params.get("arch", "x86_64"),
        "kernel_path": params.get("kernel_path", ""),
        "initrd_path": params.get("initrd_path", ""),
        "install_url": params.get("install_url", ""),
        "comment": params.get("comment", ""),
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
        os_family=dict(type="str"),
        vendor=dict(type="str", default=""),
        version=dict(type="str"),
        arch=dict(type="str", default="x86_64"),
        kernel_path=dict(type="str", default=""),
        initrd_path=dict(type="str", default=""),
        install_url=dict(type="str", default=""),
        comment=dict(type="str", default=""),
        server_url=dict(type="str", required=True),
        api_key=dict(type="str", no_log=True),
        validate_certs=dict(type="bool", default=True),
        timeout=dict(type="int", default=30),
    )

    module = AnsibleModule(
        argument_spec=module_args,
        required_if=[
            ("state", "present", ("os_family", "version")),
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
        existing = _get_distro(
            server_url, name, api_key, validate_certs, timeout,
        )
    except PxeOSAPIError as exc:
        module.fail_json(msg=f"Failed to query profile: {exc}")
        return

    changed = False
    result_profile = existing

    if state == "absent":
        if existing is not None:
            changed = True
            if not module.check_mode:
                try:
                    _delete_distro(
                        server_url, name, api_key,
                        validate_certs, timeout,
                    )
                except PxeOSAPIError as exc:
                    module.fail_json(msg=f"Failed to delete profile: {exc}")
                    return
            result_profile = None
        module.exit_json(changed=changed, profile=result_profile)
        return

    # state == "present"
    desired = _build_payload(params)

    if existing is None:
        changed = True
        if not module.check_mode:
            try:
                result_profile = _create_distro(
                    server_url, desired, api_key,
                    validate_certs, timeout,
                )
            except PxeOSAPIError as exc:
                module.fail_json(msg=f"Failed to create profile: {exc}")
                return
        else:
            result_profile = desired
    else:
        updates = _needs_update(existing, desired)
        if updates:
            changed = True
            if not module.check_mode:
                try:
                    result_profile = _update_distro(
                        server_url, name, updates, api_key,
                        validate_certs, timeout,
                    )
                except PxeOSAPIError as exc:
                    module.fail_json(msg=f"Failed to update profile: {exc}")
                    return
            else:
                result_profile = {**existing, **updates}

    module.exit_json(changed=changed, profile=result_profile)


def main():
    run_module()


if __name__ == "__main__":
    main()
