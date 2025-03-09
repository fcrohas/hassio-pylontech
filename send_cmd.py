#!/usr/bin/env python3

import argparse

from monitor import get_info, get_bat

if __name__ == "__main__":
    # parser = argparse.ArgumentParser(description="Send a command to the battery and read the response")
    # parser.add_argument("device", help="Battery IO device")
    # parser.add_argument("command", help="Command to send")
    # args = parser.parse_args()

    # response = serial_command(args.device, args.command, checkframe=False)
    response = get_bat(("192.168.2.227", 9999), 2, network=True)
    print(f"Response length: {len(response)}")
    print(response)
