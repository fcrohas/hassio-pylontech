#!/usr/bin/env python3

import argparse
import time
import json
import os
import re
from select import select
import socket

import paho.mqtt.client as mqtt


MARK_PROMPT = b"\rpylon>"
MARK_BEGIN = b"\n\r@\r\r\n"
MARK_END = b"\r\n\rCommand completed successfully\r\n\r$$\r\n" + MARK_PROMPT


def mqtt_connect(*, server, username, password, client_id):
    client = mqtt.Client(client_id=client_id)
    client.username_pw_set(username, password)
    client.connect(server)
    return client

def network_command(device, command, *, retries=1, checkframe=True):
    print(f"Sending command {command}")
    command_bytes = command.encode()
    mark_end = MARK_END if checkframe else MARK_PROMPT
    try:
        try:
            # Create a TCP/IP socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect(device)  # device should be a tuple (host, port)
        except Exception as e:
            raise RuntimeError(f"Error connecting to device {device}") from e

        sock.sendall(command_bytes + b"\n")

        response = b""
        timeout_counter = 0
        while mark_end not in response:
            if timeout_counter > 5:
                raise RuntimeError("Read operation timed out")
            sock.settimeout(1)
            try:
                data = sock.recv(256)
                if not data:
                    timeout_counter += 1
                    continue
                response += data
            except socket.timeout:
                timeout_counter += 1
                continue

        response = response.rstrip()
        if checkframe:
            if not (response.startswith(command.encode() + MARK_BEGIN) and response.endswith(mark_end)):
                raise Exception("Response frame corrupt")
            response = response[len(command) + len(MARK_BEGIN):-len(mark_end)]
        return response.decode()
    except Exception as e:
        if not retries:
            raise RuntimeError(f"Error sending command {command}")
    finally:
        try:
            sock.close()
        except Exception:
            pass
    print(f"Error sending command {command}, {retries} retries remaining")
    time.sleep(0.1)
    try:
        network_command(device, "", retries=0, checkframe=False) # Try to clear prompt and recover
    except Exception:
        pass
    return network_command(device, command, retries=retries-1)

def serial_command(device, command, *, retries=1, checkframe=True):
    print(f"Sending command {command}")
    command_bytes = command.encode()
    mark_end = MARK_END if checkframe else MARK_PROMPT
    try:
        try:
            file = os.open(device, os.O_RDWR | os.O_NONBLOCK)
        except Exception as e:
            raise RuntimeError(f"Error opening device {device}") from e

        ready = select([], [file], [], 1)
        if not ready[1]:
            raise RuntimeError("Write operation timed out")
        os.write(file, command_bytes + b"\n")

        response = b""
        timeout_counter = 0
        while mark_end not in response:
            if timeout_counter > 5:
                raise RuntimeError("Read operation timed out")
            ready = select([file], [], [], 1)
            if not ready[0]:
                timeout_counter += 1
                continue
            response += os.read(file, 256)

        response = response.rstrip()
        if checkframe:
            if not (response.startswith(command.encode() + MARK_BEGIN) and response.endswith(mark_end)):
                raise Exception("Response frame corrupt")
            response = response[len(command) + len(MARK_BEGIN):-len(mark_end)]
        return response.decode()
    except Exception as e:
        if not retries:
            raise RuntimeError(f"Error sending command {command}")
    finally:
        try:
            os.close(file)
        except Exception:
            pass
    print(f"Error sending command {command}, {retries} retries remaining")
    time.sleep(0.1)
    try:
        serial_command(device, "", retries=0, checkframe=False) # Try to clear prompt and recover
    except Exception:
        pass
    return serial_command(device, command, retries=retries-1)


def get_power(device, network=False):
    if network:
        response = network_command(device, "pwr")
    else:
        response = serial_command(device, "pwr")
    try:
        lines = response.split("\n")

        colstart = [0]
        for m in re.findall(r"([^ ]+ +)", lines[0].rstrip()):
            colstart.append(colstart[-1] + len(m))

        def getcell(line, cellno):
            linelen = len(line)
            offset1 = min(linelen, colstart[cellno])
            if offset1 and line[offset1-1] != " ":
                offset1 -= 1
            offset2 = min(linelen, colstart[cellno+1] if cellno+1 < len(colstart) else len(line))
            if line[offset2-1] != " ":
                offset2 -= 1
            return line[offset1:offset2].strip()

        headers = [getcell(lines[0], i) for i in range(len(colstart))]

        items = []
        for line in lines[1:]:
            values = [getcell(line, i) for i in range(len(colstart))]
            item = dict(zip(headers, values))
            if item["Base.St"] == "Absent":
                continue

            for k in ("Power", "Volt", "Curr", "Tempr", "Tlow", "Thigh", "Vlow", "Vhigh", "MosTempr"):
                try:
                    item[k] = int(item[k])
                except Exception:
                    pass
            try:
                item["Coulomb"] = int(item["Coulomb"][:-1])
            except Exception:
                pass
            items.append(item)

        return items
    except Exception as e:
        raise RuntimeError(f"Error parsing power ({response})") from e


def send_data(client, topic, data):
    try:
        client.publish(topic, data, 0, True)
    except Exception as e:
        raise RuntimeError("Error sending data to mqtt server") from e


def main(
    *,
    device,
    host,
    port,
    mode,
    mqtt_server,
    mqtt_user,
    mqtt_pass,
    mqtt_client_id,
    mqtt_topic,
    sleep_iteration=0,
):
    client = mqtt_connect(
        server=mqtt_server,
        username=mqtt_user,
        password=mqtt_pass,
        client_id=mqtt_client_id,
    )
    print(f"Reading from battery\n")

    while True:
        start = time.time()
        if mode:
            data = json.dumps(get_power((host, int(port)), network=True))
        else:
            data = json.dumps(get_power(device))
        print("power", data, "\n")
        send_data(client, mqtt_topic, data)

        time.sleep(sleep_iteration)


if __name__ == "__main__":
    def env(var, val=None):
        return {"default": os.environ.get(var)} if os.environ.get(var) else \
               {"default": val} if val is not None else \
               {"required": True}
    parser = argparse.ArgumentParser(description="""
        Monitor battery parameters and send them to an MQTT server.
        Arguments can also be set using their corresponding environment variables.
    """)
    parser.add_argument("--mode", **env("MODE"), help="Connection mode : network or serial")
    parser.add_argument("--host", **env("HOST"), help="Remote Host Battery IO device")
    parser.add_argument("--port", **env("PORT"), help="Remote Port Battery IO device")
    parser.add_argument("--device", **env("DEVICE"), help="Battery IO device")
    parser.add_argument("--mqtt-server", **env("MQTT_SERVER"), help="MQTT server address")
    parser.add_argument("--mqtt-user", **env("MQTT_USER"), help="MQTT username")
    parser.add_argument("--mqtt-pass", **env("MQTT_PASS"), help="MQTT password")
    parser.add_argument("--mqtt-client-id", **env("MQTT_CLIENT_ID"), help="MQTT client id")
    parser.add_argument("--mqtt-topic", **env("MQTT_TOPIC"), help="MQTT topic for data")
    parser.add_argument("--sleep-iteration", type=float, **env("SLEEP_ITERATION", 5), help="Seconds between iteration starts")
    args = parser.parse_args()

    main(
        device=args.device,
        host=args.host,
        port=args.port,
        mode=args.mode == "network",
        mqtt_server=args.mqtt_server,
        mqtt_user=args.mqtt_user,
        mqtt_pass=args.mqtt_pass,
        mqtt_client_id=args.mqtt_client_id,
        mqtt_topic=args.mqtt_topic,
        sleep_iteration=args.sleep_iteration,
    )
