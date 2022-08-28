#!/usr/bin/env python3
"""Lambda energy manager connector

Read data from an energy manager and send it to a lambda heatpump
in order to increase self-consumption.

usage:

python3 lambda-modbus-tcp.py [-h]

"""

import argparse
import logging
import time
from pymodbus.client.sync import ModbusTcpClient
from pymodbus.exceptions import ModbusIOException

# setup logging
FORMAT = "%(asctime)-15s %(levelname)-8s %(module)-15s:%(lineno)-8s %(message)s"
logging.basicConfig(format=FORMAT)
_logger = logging.getLogger()


# Meter implementations
class Meter:
    def read(self):
        raise NotImplementedError


class SolarEdge(Meter):

    def __init__(self, host, port, unit):
        import solaredge_modbus

        self.meters = None
        _logger.info("Connecting to SE inverter {}:{}:{}".format(host, port, unit))
        self.inverter = solaredge_modbus.Inverter(host=host, port=port, unit=unit)
        self.reconnect()

    def read(self):
        if self.inverter.connected() is False:
            self.reconnect()
        value = 0
        for k in self.meters.keys():
            value += self.meters[k].read_all()['power']
        return value

    def reconnect(self):
        self.inverter.connect()
        if not self.inverter.connected():
            raise RuntimeError("Failed to connect to solar edge inverter")
        self.meters = self.inverter.meters()


def create_meter(t, host, port, unit):
    if t == "se":
        return SolarEdge(host, port, unit)
    raise KeyError("unknown meter type")


# heatpump connectors
class HeatPump:
    def write(self, value):
        raise NotImplementedError


class Lambda(HeatPump):
    POWER_REGISTER = 102

    @staticmethod
    def __negative_transform(v):
        if v < 0:
            return 2 ** 16
        return 2 ** 16 - v

    @staticmethod
    def __positive_transform(v):
        return v

    def __init__(self, host, port, value_transform):
        self.heat_pump = ModbusTcpClient(host, port=port)
        self.reconnect()
        if value_transform == "negative":
            self.transform = self.__negative_transform
        elif value_transform == "positive":
            self.transform = self.__postive_transform
        else:
            raise KeyError("unknown value transform")

    def write(self, value):
        self.check()
        r = self.heat_pump.write_registers(102, self.transform(value))
        if r is ModbusIOException:
            raise RuntimeError("Failed to write value")
        if r.isError():
            raise RuntimeError("Error writing value")
        _logger.debug("Wrote value {} to lambda heat pump".format(value))

    def check(self):
        r = self.heat_pump.read_holding_registers(1)
        if r is ModbusIOException:
            self.reconnect()
            r = self.heat_pump.read_holding_registers(1)
        if r.registers[0] == 0:
            raise RuntimeError("Lambda heatpump is turned off")
        if r.registers[0] == 3:
            raise RuntimeError("Lambda heatpump reports error")

    def reconnect(self):
        self.heat_pump.connect()


def create_sink(t, host, port, value_transform):
    if t == "lambda":
        return Lambda(host, port, value_transform)
    raise KeyError("unknown heat pump type")


# Daemon

def loop(source, dest, interval, daemon):
    while True:
        try:
            dest.write(source.read())
            time.sleep(interval)
        except Exception as e:
            if not daemon:
                raise e
            else:
                _logger.error("Failed to read/write energy value", e)
                time.sleep(interval)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Connect energy manager and lambda heatpump"
    )
    parser.add_argument(
        "--source-type",
        choices=["se"],
        help='"se": Solaredge',
        type=str,
        default="se"
    )

    parser.add_argument(
        "--source-host",
        help='source host address',
        type=str,
        required=True
    )

    parser.add_argument(
        "--source-port",
        help='source port',
        type=int,
        default=502
    )

    parser.add_argument(
        "--source-unit",
        help='source unit',
        type=int,
        default=1
    )

    parser.add_argument(
        "--dest-host",
        help='heat pump host address',
        type=str,
        required=True
    )

    parser.add_argument(
        "--dest-port",
        help="heat pump port to use",
        type=int,
        default=502
    )

    parser.add_argument(
        "--dest-type",
        choices=["negative", "positive"],
        help='"negative": send excess as negative value, "positive": send excess as negative value',
        type=str,
        default="negative"
    )

    parser.add_argument(
        "-d",
        "--daemon",
        help='run in daemon mode',
        type=bool,
        default=False
    )

    parser.add_argument(
        "-i",
        "--interval",
        help='interval in seconds for reading/writing',
        type=float,
        default=1.0
    )

    parser.add_argument(
        "--log",
        choices=["critical", "error", "warning", "info", "debug"],
        help='"critical", "error", "warning", "info" or "debug"',
        type=str,
    )

    args = parser.parse_args()

    _logger.setLevel(args.log.upper() if args.log else logging.INFO)

    source = create_meter(args.source_type, args.source_host, args.source_port, args.source_unit)
    dest = create_sink("lambda", args.dest_host, args.dest_port, args.dest_type)
    loop(source, dest, args.interval, args.daemon)
