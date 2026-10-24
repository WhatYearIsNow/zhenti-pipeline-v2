"""ISO-03 验证：仓库级网络守卫确实生效（conftest.py）。

守卫在连接层拒绝，因此这里使用 TEST-NET-3 文档地址，任何真实出网都不会发生。
"""
import socket

import pytest


def test_create_connection_is_refused():
    with pytest.raises(OSError, match="ISO-03"):
        socket.create_connection(("203.0.113.1", 80), timeout=1)


def test_socket_connect_is_refused():
    with pytest.raises(OSError, match="ISO-03"):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.connect(("203.0.113.1", 80))
        finally:
            s.close()


def test_dns_resolution_is_refused():
    with pytest.raises(OSError, match="ISO-03"):
        socket.getaddrinfo("example.invalid", 80)
