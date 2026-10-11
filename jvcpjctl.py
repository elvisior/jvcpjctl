#!/usr/bin/env python3
"""
JVC DLT-20 (DLA series) projector LAN control (TCP 20554),
per the DLA Mobile User Guide (b5a-3961-01).

Usage:
  jvcpjctl.py                  # query power status
  jvcpjctl.py on               # power on
  jvcpjctl.py off              # power off
  jvcpjctl.py [--ip IP]        # --ip: target a different projector
                                #   (default 192.168.1.200)
  e.g.  jvcpjctl.py --ip 192.168.1.233 on

Protocol (fast variant):
  1. TCP connect (short timeout, few retries)
  2. Server greeting "PJ_OK"
  3. Client  "PJREQ"            -> server "PJACK"
  4. Query:
     Client  3F 89 01 50 57 0A  (reference command, power status)
     Server  06 89 01 50 57 0A  (ack)
     Server  40 89 01 50 57 3X 0A  (data; state byte 3X)
     State: 0x30 standby | 0x31 on | 0x32 cool-down | 0x33 warm-up | 0x34 error
  5. Power command (on/off):
     On:  21 89 01 50 57 31 0A   Off: 21 89 01 50 57 30 0A
     Server acks with 06 89 01 50 57 0A

Exit codes: 0 = answered/acked | 1 = unreachable | 2 = protocol error
"""

import argparse
import socket
import sys
import time

HOST = "192.168.1.200"
PORT = 20554
CONNECT_TIMEOUT = 1.2      # per connect attempt
READ_TIMEOUT = 1.2         # per read window
RETRIES = 3                # connect attempts (flapping port)
RETRY_DELAY = 0.5          # seconds between attempts

STATE = {
    b"0": "Standby (off)",
    b"1": "On",
    b"2": "Cooling down",
    b"3": "Warm-up",
    b"4": "Error state",
}

QUERY_FRAME = bytes.fromhex("3f890150570a")
POWER_ON_FRAME = bytes.fromhex("2189015057310a")
POWER_OFF_FRAME = bytes.fromhex("2189015057300a")
QUERY_ACK_PREFIX = bytes.fromhex("4089015057")  # data frame prefix
ACK_PREFIX = b"\x06"                            # generic ack marker


def recv_until(sock, buf, deadline):
    """Read until deadline; returns accumulated buffer."""
    while time.monotonic() < deadline:
        try:
            sock.settimeout(max(0.05, deadline - time.monotonic()))
            chunk = sock.recv(1024)
            if chunk:
                buf += chunk
            else:
                break
        except (socket.timeout, BlockingIOError):
            pass
    return buf


def connect():
    last_err = None
    for attempt in range(RETRIES):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.settimeout(CONNECT_TIMEOUT)
            sock.connect((HOST, PORT))
            return sock
        except OSError as e:
            last_err = e
            sock.close()
            if attempt < RETRIES - 1:
                time.sleep(RETRY_DELAY)
    print(f"Projector unreachable at {HOST}:{PORT}")
    print(f"  last reason: {last_err}")
    sys.exit(1)


def handshake(sock):
    greeting = recv_until(sock, b"", time.monotonic() + READ_TIMEOUT)
    if b"PJ_OK" not in greeting:
        print(f"Protocol error: no PJ_OK greeting (got: {greeting[:32]!r})")
        sys.exit(2)

    sock.sendall(b"PJREQ")
    buf = recv_until(sock, b"", time.monotonic() + READ_TIMEOUT)
    if b"PJACK" not in buf:
        print(f"Protocol error: no PJACK (got: {buf[:32]!r})")
        sys.exit(2)


def query_status(sock):
    sock.sendall(QUERY_FRAME)
    data = recv_until(sock, b"", time.monotonic() + READ_TIMEOUT)  # ack + data frames
    for state in (b"0", b"1", b"2", b"3", b"4"):
        if QUERY_ACK_PREFIX + state + b"\n" in data:
            print(f"Projector at {HOST}: {STATE[state]}")
            return
    print(f"Protocol error: no status frame in response (got: {data[:48]!r})")
    sys.exit(2)


def send_power(sock, on: bool):
    frame = POWER_ON_FRAME if on else POWER_OFF_FRAME
    sock.sendall(frame)
    data = recv_until(sock, b"", time.monotonic() + READ_TIMEOUT)
    if ACK_PREFIX in data:
        print(f"Projector at {HOST}: power {'on' if on else 'off'} command accepted")
        return
    print(f"Protocol error: no ack for power command (got: {data[:48]!r})")
    sys.exit(2)


def main():
    global HOST
    p = argparse.ArgumentParser(
        prog="jvcpjctl",
        description="Control a JVC DLT-20 (DLA) projector over LAN."
    )
    p.add_argument("state", nargs="?", choices=["on", "off"],
                   help="power on / off (default: query status)")
    p.add_argument("--ip", default=HOST, metavar="IP",
                   help="projector IP address (default: 192.168.1.200)")
    args = p.parse_args()

    HOST = args.ip

    sock = connect()
    try:
        handshake(sock)
        if args.state is None:
            query_status(sock)
        else:
            send_power(sock, on=(args.state == "on"))
    finally:
        sock.close()


if __name__ == "__main__":
    main()
