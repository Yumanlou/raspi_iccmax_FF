# Raspberry Pi PMBus ICC_MAX modification Tool

This repository provides a Python utility to read and modify ICC_MAX limits on PMBus-compatible VRM controllers using a Raspberry Pi I²C interface.
It is a port of the original MCP2221-based C# implementation, adapted to run directly on `/dev/i2c-1` with `smbus2`.

**Make sure you check the original work by RolloZ170 first!**
https://forums.servethehome.com/index.php?threads/vrm-modify-icc_max-to-run-high-tdc-oem-cpu.38686/

Supported controllers:

* **PXE1610C**
* **MP2955A**
* **TPS53678**
* **TPS53679**

Functions included:

* Device identification
* ICC_MAX read-out
* ICC_MAX update (e.g., to `0xFF00`)
* Remaining attempt counter read-out (Primarion family)
* NVM commit sequences where required

> **Warning:** Modifying VRM configuration can cause hardware instability or damage if misused. Proceed only if you fully understand PMBus behavior and VRM power delivery constraints.

---

## Requirements

### Hardware

* Raspberry Pi (tested on Pi 3/4/5), or any similar devices
* I²C enabled and wired pins to VRM or bus on the target board

### Software

Install prerequisites:

```bash
sudo apt-get update
sudo apt-get install -y python3-pip python3-smbus2 i2c-tools
```

Enable I²C:

```bash
sudo raspi-config
# Interface Options → I2C → Enable
sudo reboot
```

---

## Usage

### Command Syntax (matches original C# version)

```
python3 raspi_iccmax_FF.py -scan START END
python3 raspi_iccmax_FF.py -PXE1610C ADDR [ADDR2]
python3 raspi_iccmax_FF.py -MP2955A ADDR [ADDR2]
python3 raspi_iccmax_FF.py -TPS53679 ADDR [ADDR2]
python3 raspi_iccmax_FF.py -TPS53678 ADDR [ADDR2]
```

### Examples

Scan the PMBus address space:

```bash
python3 raspi_iccmax_FF.py -scan 10 77
```

Modify ICC_MAX on a PXE1610C at 0x5A and 0x5C:

```bash
python3 raspi_iccmax_FF.py -PXE1610C 5A 5C
```

Read/write for a Texas Instruments VRM:

```bash
python3 raspi_iccmax_FF.py -TPS53679 70
```

---

## Typical Output

* Device ID detection
* Page setting and register reads
* ICC_MAX values before/after update
* Remaining attempt counter (Primarion only)
* NVM commit results

Successful modification example:

```
PXE1610C found: starting modd
set smb_password=OK
ICC_MAX=E400
Write ICC_MAX=OK
set nvm_password=OK
upload_cfg_send_byte=OK
clear nvm_password=OK
PXE1610C modd successful
```

---

## License

MIT License (same as original C# implementation unless otherwise specified).

---

## Credits

* RolloZ170 for Original MCP2221a-based implementation
