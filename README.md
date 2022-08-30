# lambda-heatpump-modbus-tcp
(PV Überschuss Steuerung für Lambda Wärmepumpen)

Simple script to connect energy meter with a lambda heatpump over modbus tcp

Supports:

- Solaredge energy meter (using [solaredge modbus](https://pypi.org/project/solaredge-modbus/))
- Lambda heatpump EU08L, EU13L

Example usage:

```
python3 lambda-modbus-tcp.py --source-host 192.168.0.106 --dest-host 192.168.0.188 --source-port 1502 --source-unit=4
```
