#!/usr/bin/env python3
"""Lambda energy manager connector

Read data from an energy manager and send it to a lambda heatpump
in order to increase self-consumption.

usage:

python3 lambda-modbus-tcp.py [-h] [--source-type {se}] --source-host SOURCE_HOST [--source-port SOURCE_PORT] [--source-unit SOURCE_UNIT] --dest-host
                            DEST_HOST [--dest-port DEST_PORT] [--dest-type {negative,positive}] [-d] [-i INTERVAL]
                            [--log {critical,error,warning,info,debug}]

Connect energy manager and lambda heatpump

optional arguments:
  -h, --help            show this help message and exit
  --source-type {se}    "se": Solaredge
  --source-host SOURCE_HOST
                        source host address
  --source-port SOURCE_PORT
                        source port
  --source-unit SOURCE_UNIT
                        source unit
  --dest-host DEST_HOST
                        heat pump host address
  --dest-port DEST_PORT
                        heat pump port to use
  --dest-type {negative,positive}
                        "negative": send excess as negative value, "positive": send excess as is
  -d, --daemon          run in daemon mode (ignores exceptions)
  -i INTERVAL, --interval INTERVAL
                        interval in seconds for reading/writing
  --log {critical,error,warning,info,debug}
                        "critical", "error", "warning", "info" or "debug"

"""

import argparse
import logging
import time
from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ModbusIOException
import math
# setup logging
#FORMAT = "%(asctime)-15s %(levelname)-8s %(module)-15s:%(lineno)-8s %(message)s"
FORMAT = "%(asctime)-15s %(levelname)-8s %(message)s"
logging.basicConfig(format=FORMAT)
_logger = logging.getLogger()


# Meter implementations
class Meter:
    def read(self):
        raise NotImplementedError

class Fronius(Meter):

    def __init__(self, host, port, unit):
        _logger.info("Connecting to Fronius SmartMeter {}:{}:{}".format(host, port, unit))
        self.smartMeter = ModbusTcpClient(host, port=port)
        self.unit = unit
        self.reconnect()

    def reconnect(self):
        self.smartMeter.connect()

    def read(self):
        power = self.smartMeter.read_holding_registers(40087, 1, self.unit)
        
        _logger.debug("Power raw: {}".format(power.registers[0]))
        p1 = twos_comp(power.registers[0], 16)
        _logger.debug("Power twos_comp: {}".format(p1))
        factor = self.smartMeter.read_holding_registers(40091, 1, self.unit)
        _logger.debug("Factor: {}".format(factor.registers[0]))
        powerScaled = p1* math.pow(10, twos_comp(factor.registers[0], 16))
        _logger.info("Power Scaled: {}".format(powerScaled))

        return powerScaled

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


class StaticValue(Meter):

    def __init__(self, value):
        self.value = value

    def read(self):
        return self.value


def create_meter(t, host, port, unit, value):
    if t == "se":
        return SolarEdge(host, port, unit)
    elif t == "fsm":
        return Fronius(host, port, unit)
    elif t == "static":
        return StaticValue(value)
    raise KeyError("unknown meter type")


# heatpump connectors
class HeatPump:
    def write(self, value):
        raise NotImplementedError


class Lambda(HeatPump):
    POWER_REGISTER = 102

    @staticmethod
    def __negative_transform(v):
        if v <= 0:
            return min(-v, 0x7fff)
        elif v < 0x8000 :
            return 0x10000 - v
        return 0x8000


    @staticmethod
    def __positive_transform(v):
        return v

    def __init__(self, host, port, value_transform):
        _logger.info("Connecting to Lambda heat pump {}:{}".format(host, port))
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


def create_dest(t, host, port, value_transform):
    if t == "lambda":
        return Lambda(host, port, value_transform)
    raise KeyError("unknown heat pump type")


# Daemon

def loop(source, dest, interval, daemon):
    while True:
        try:
            val = source.read()
            if dest:
                dest.write(val)
            time.sleep(interval)
        except Exception as e:
            if not daemon:
                raise e
            else:
                _logger.error("Failed to read/write energy value, automatically retrying", exc_info=1)
                time.sleep(interval)

def twos_comp(val, bits):
    #compute the 2's complement of int value val
    if (val & (1 << (bits - 1))) != 0: # if sign bit is set e.g., 8bit: 128-255
        val = val - (1 << bits)        # compute negative value
    return val                         # return positive value as is



if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Connect energy manager and lambda heatpump"
    )
    parser.add_argument(
        "--source-type",
        choices=["se", "fsm", "static"],
        help='"se": Solaredge, "fsm": ForniusSmartMeter, "static": Simulate a static value',
        type=str,
        default="se"
    )

    parser.add_argument(
        "--source-host",
        help='source host address',
        type=str,
        required=False
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
        "--source-value",
        help='source value',
        type=int,
        default=2000
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
        help='"negative": send excess as negative value, "positive": send excess as is',
        type=str,
        default="negative"
    )

    parser.add_argument(
        "-d",
        "--daemon",
        action='store_true',
        help='run in daemon mode (ignores exceptions)'
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

    source = create_meter(args.source_type, args.source_host, args.source_port, args.source_unit, args.source_value)
    dest = create_dest("lambda", args.dest_host, args.dest_port, args.dest_type)
    loop(source, dest, args.interval, args.daemon)

    #loop(source, None, 5, args.daemon)