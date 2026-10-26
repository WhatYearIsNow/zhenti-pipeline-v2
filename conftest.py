"""仓库级测试隔离守卫（方案 S1 · ISO-03：默认测试无网络）。

在连接层拒绝 IPv4/IPv6 出网与 DNS 解析，任何测试（含收集阶段）均不得发起网络 I/O；
文件系统副作用由各测试用 tempfile/tmp_path 自行限定（ISO-02）。
历史上不存在需要网络回环的用例；如未来引入本地替身服务，须显式加白并说明。
"""

import socket

import pytest


class NetworkDisabled(OSError):
    """测试环境下发起网络连接（ISO-03 违规）。"""


def _refuse_connect(self, address):
    raise NetworkDisabled(f"测试默认禁止网络连接（ISO-03）: {address!r}")


def _refuse_create_connection(address, *args, **kwargs):
    raise NetworkDisabled(f"测试默认禁止网络连接（ISO-03）: {address!r}")


def _refuse_getaddrinfo(*args, **kwargs):
    raise NetworkDisabled("测试默认禁止 DNS 解析（ISO-03）")


socket.socket.connect = _refuse_connect
socket.create_connection = _refuse_create_connection
socket.getaddrinfo = _refuse_getaddrinfo

pytest_network_guard_active = True
