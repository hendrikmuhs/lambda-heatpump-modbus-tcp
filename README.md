# lambda-heatpump-modbus-tcp
(PV Überschuss Steuerung für Lambda Wärmepumpen)

Simple script to connect energy meter with a lambda heatpump over modbus tcp to prioritize execution at times of excess photovoltaic production:

![heatpump-runtime](https://user-images.githubusercontent.com/7126422/190114167-42f43732-50fe-4749-8e3d-93b72817e8d0.png)

(red: consumption, green: pv production, blue: self-consumption)

Supports:

- Solaredge energy meter (using [solaredge modbus](https://pypi.org/project/solaredge-modbus/))
- Lambda heatpump EU08L, EU13L

Example usage:

```
python3 lambda-modbus-tcp.py --source-host 192.168.0.106 --dest-host 192.168.0.188 --source-port 1502 --source-unit=4
```

Demo mode:

Using the "static meter" you can simulate a given value. E.g. to write 1500W use:

```
python3 lambda-modbus-tcp.py --source-type static --dest-host 192.168.0.188 -d -i 5 --source-value 1500
```
