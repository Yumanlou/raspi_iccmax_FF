#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Raspberry Pi I2C PMBus/VRM tool
移植自你原来的 C# 逻辑，保留分页(Page=0x00)、命令寄存器写读、重试策略、设备识别与 ICC_MAX 修改。
地址全部为 7 位 I2C 地址（十六进制），不要左移。
"""

import sys
import time
import argparse
from smbus2 import SMBus, i2c_msg

BUS_ID = 1              # /dev/i2c-1
RETRY_RW = 4           # 读写重试次数
RETRY_SCAN = 2         # 扫描时的读重试
I2C_FREQUENCY = 400000  # 这里仅做注释提醒，速率由内核驱动配置

# ---------- 基础 I2C/SMBus 工具 ----------

def write_block(bus: SMBus, addr7: int, data: bytes) -> int:
    """写一坨字节，调用者负责把命令码放在 data[0]（如果需要）"""
    try:
        wr = i2c_msg.write(addr7, data)
        bus.i2c_rdwr(wr)
        return 0
    except Exception:
        return -1

def read_block(bus: SMBus, addr7: int, reg: int, nbytes: int) -> (int, bytes):
    """先写入寄存器 reg，再读 nbytes 字节"""
    try:
        wr = i2c_msg.write(addr7, bytes([reg]))
        rd = i2c_msg.read(addr7, nbytes)
        bus.i2c_rdwr(wr, rd)
        return 0, bytes(rd)
    except Exception:
        return -1, b''

def vrm_write_block(bus: SMBus, addr7: int, page: int, payload: bytes) -> int:
    """如果 page>=0，则先 set PAGE: [0x00, page]，然后写 payload。带重试。"""
    tries = 0
    while tries < RETRY_RW:
        if tries > 0:
            print(f" try #{tries}")
        tries += 1
        rc = 0
        if page >= 0:
            rc = write_block(bus, addr7, bytes([0x00, page]))
        if rc == 0:
            rc = write_block(bus, addr7, payload)
        if rc == 0:
            return 0
    return -1

def vrm_read_block(bus: SMBus, addr7: int, page: int, reg: int, nbytes: int) -> (int, bytes):
    """如果 page>=0，则先 set PAGE: [0x00, page]，然后 read reg。带重试。"""
    tries = 0
    while tries < RETRY_RW:
        if tries > 0:
            print(f" retry#{tries}")
        tries += 1
        rc = 0
        if page >= 0:
            rc = write_block(bus, addr7, bytes([0x00, page]))
        if rc == 0:
            rc, data = read_block(bus, addr7, reg, nbytes)
            if rc == 0:
                return 0, data
    return -1, b''

def scan_read_block(bus: SMBus, addr7: int, page: int, reg: int, nbytes: int) -> (int, bytes):
    """用于扫描阶段的快速读，重试次数较少。"""
    tries = 0
    while tries < RETRY_SCAN:
        tries += 1
        rc = 0
        if page >= 0:
            rc = write_block(bus, addr7, bytes([0x00, page]))
        if rc == 0:
            rc, data = read_block(bus, addr7, reg, nbytes)
            if rc == 0:
                return 0, data
    return -1, b''

# ---------- 设备专用逻辑 ----------

def pxe1610_set_icc_max(bus: SMBus, addr7: int) -> int:
    # 检测：Page00 FD==0xB3；Page4F 1A==0x00；Page4F 32==0x15 0x04
    rc, b00_fd = vrm_read_block(bus, addr7, 0x00, 0xFD, 1)
    print(f"ReadBlock( Page00,cmdFD,1)={'??' if rc else b00_fd[0]:02X}" + ("\n" if rc==0 else " =Error"))

    if rc == 0 and b00_fd[0] == 0xB3:
        rc, b4f_1a = vrm_read_block(bus, addr7, 0x4F, 0x1A, 1)
        print("ReadBlock( Page4F,cmd1A,1)=" + (f"{b4f_1a[0]:02X}\n" if rc==0 else "Error"))
    else:
        print("Device detection error\n")
        return -1

    if rc == 0 and b4f_1a[0] == 0x00:
        rc, b4f_32 = vrm_read_block(bus, addr7, 0x4F, 0x32, 2)
        print("ReadBlock( Page4F,cmd32,2)=" + (f"{b4f_32[0]:02X}{b4f_32[1]:02X}\n" if rc==0 else "Error"))
    else:
        print("PXE1610C not found\n")
        return -1

    if rc == 0 and b4f_32[0] == 0x15 and b4f_32[1] == 0x04:
        print("PXE1610C found: starting modd\n")
    else:
        print("PXE1610C not found\n")
        return -1

    # 设置 SMB 密码 (Page3F: [0x27,0x7C,0xB3])
    rc = vrm_write_block(bus, addr7, 0x3F, bytes([0x27, 0x7C, 0xB3]))
    print("set smb_password=" + ("OK" if rc == 0 else "Error"))
    if rc != 0: return -1

    # 读 ICC_MAX (Page20, 0x73)
    rc, icc = vrm_read_block(bus, addr7, 0x20, 0x73, 2)
    if rc == 0:
        print(f"ICC_MAX={icc[0]:02X}{icc[1]:02X}\n")
        if icc[0] == 0xFF:
            print(" ICC_MAX is 255A - modification skipped.\n")
            return 0
    else:
        print("Read ICC_MAX=Error\n")
        return -1

    # 读剩余尝试次数 (Page50, 0x82)
    rc, att = vrm_read_block(bus, addr7, 0x50, 0x82, 2)
    if rc == 0:
        tmp = (att[1] << 2) & 0xFF
        remain = (tmp | (att[0] >> 6)) & 0xFF
        print(f" old remaining attempts= {remain:02X}")
    else:
        print("read attempts=Error")

    # 写 ICC_MAX=0xFF00 (Page20: 写 [0x73, 0xFF, 0x00])
    rc = vrm_write_block(bus, addr7, 0x20, bytes([0x73, 0xFF, 0x00]))
    print("Write ICC_MAX=" + ("OK" if rc == 0 else "Error"))
    if rc != 0: return -1

    # 设置 NVM 密码
    rc = vrm_write_block(bus, addr7, 0x3F, bytes([0x29, 0xD7, 0xEF]))
    print("set nvm_password=" + ("OK" if rc == 0 else "Error"))
    if rc != 0: return -1

    # 触发上传
    rc = vrm_write_block(bus, addr7, 0x3F, bytes([0x34]))
    print("upload_cfg_send_byte=" + ("OK" if rc == 0 else "Error"))
    time.sleep(1)

    # 清除 NVM 密码
    rc = vrm_write_block(bus, addr7, 0x3F, bytes([0x29, 0x00, 0x00]))
    print("clear nvm_password=" + ("OK" if rc == 0 else "Error"))
    if rc != 0: return -1

    # 再读尝试次数
    rc, att2 = vrm_read_block(bus, addr7, 0x50, 0x82, 2)
    if rc == 0:
        tmp = (att2[1] << 2) & 0xFF
        remain = (tmp | (att2[0] >> 6)) & 0xFF
        print(f" new remaining attempts= {remain:02X}")

    if rc == 0:
        print("PXE1610C modd successful\n")
        return 0
    else:
        print("PXE1610C modd error\n")
        return -1

def mp2955a_set_icc_max(bus: SMBus, addr7: int) -> int:
    # 识别：Page00 BF==0x25 0x55（输出打印顺序和原逻辑一致）
    rc, bf = vrm_read_block(bus, addr7, 0x00, 0xBF, 2)
    print("ReadBlock( Page00,cmdBF,2)=" + (f"{bf[1]:02X}{bf[0]:02X}\n" if rc==0 else "Error\n"))
    if rc != 0:
        print("Device detection error\n")
        return -1

    if bf[0] == 0x55 and bf[1] == 0x25:
        print("MP2955A found: starting modd\n")
    else:
        print("PXE1610C not found\n")  # 按你原代码的“迷惑输出”保持风格
        return -1

    # 读 EF (ICC_MAX)
    rc, v = vrm_read_block(bus, addr7, 0x00, 0xEF, 1)
    print("ReadBlock( Page00,cmdEF,1) " + (f"ICC_MAX={v[0]:02X}\n" if rc==0 else "=Error\n"))
    if rc != 0: return -1
    if v[0] == 0xFF:
        print(" ICC_MAX already 255A - modification skipped.\n")
        return 0

    # 写 EF FF
    rc = vrm_write_block(bus, addr7, 0x00, bytes([0xEF, 0xFF]))
    print("WriteBlock( Page00,cmdEF,FF)=" + ("OK" if rc == 0 else "Error"))
    if rc != 0: return -1

    # 读回 EF
    rc, v2 = vrm_read_block(bus, addr7, 0x00, 0xEF, 1)
    print("ReadBlock( Page00,cmdEF,1) " + (f"ICC_MAX={v2[0]:02X}\n" if rc==0 else "Error\n"))

    # 执行存储/应用（原逻辑用 0x15）
    rc = vrm_write_block(bus, addr7, 0x00, bytes([0x15]))
    print("WriteBlock( Page00,cmd15)=" + ("OK" if rc == 0 else "Error"))
    time.sleep(1)

    if rc == 0:
        print("MP2955A modd successful\n")
        return 0
    else:
        print("MP2955A modd error\n")
        return -1

def tps53679_set_icc_max(bus: SMBus, addr7: int) -> int:
    # 识别：Page00 AD== 0x01 0x79 或 0x78
    rc, ad = vrm_read_block(bus, addr7, 0x00, 0xAD, 2)
    print("ReadBlock( Page00,cmdAD,2)=" + (f"{ad[0]:02X}{ad[1]:02X}\n" if rc==0 else "Error"))
    if rc != 0:
        print("Device detection error\n")
        return -1

    if ad[0] == 0x01 and ad[1] in (0x79, 0x78):
        print("TPS53679 found: starting modd" if ad[1] == 0x79 else "TPS53678 found: starting modd")
    else:
        print("TPS53679 not found\n")
        return -1

    # 读 DA（ICC_MAX 低字节在前）
    rc, da = vrm_read_block(bus, addr7, 0x00, 0xDA, 2)
    print("ReadBlock( Page00,cmdDA,2) " + (f"{da[0]:02X}{da[1]:02X}\n" if rc==0 else "Error"))
    if rc != 0: return -1
    if da[0] == 0xFF:
        print(" ICC_MAX already 255A - modification skipped.\n")
        return 0

    # 写 DA FF 00
    rc = vrm_write_block(bus, addr7, 0x00, bytes([0xDA, 0xFF, 0x00]))
    print("WriteBlock( Page00,cmdDA,FF 00)=" + ("OK" if rc == 0 else "Error"))
    if rc != 0: return -1

    # 读回
    rc, da2 = vrm_read_block(bus, addr7, 0x00, 0xDA, 2)
    print("ReadBlock( Page00,cmdDA,2)=" + (f"{da2[0]:02X}{da2[1]:02X}\n" if rc==0 else "Error"))

    # STORE/应用（原逻辑用 0x11）
    rc = vrm_write_block(bus, addr7, 0x00, bytes([0x11]))
    print("WriteBlock( Page00,cmd11)=" + ("OK" if rc == 0 else "Error"))
    time.sleep(1)

    if rc == 0:
        print("TPS53678/TPS53679 modd successful\n")
        return 0
    else:
        print("TPS53678/TPS53679 modd error\n")
        return -1

# ---------- 扫描 ----------

def scan_pmbus(bus: SMBus, start_addr: int, end_addr: int) -> int:
    a = start_addr
    while a <= end_addr:
        print(f"scanning at addr: {a:02X}")
        present = True
        # 简易探测：尝试读寄存器 0x00 一个字节
        try:
            rc, _ = read_block(bus, a, 0x00, 1)
            if rc != 0:
                present = False
        except Exception:
            present = False

        if present:
            print(f" found device at addr: {a:02X}")

            # ISL69127 (经验式判断)
            rc, ad5 = scan_read_block(bus, a, 0x00, 0xAD, 5)
            if rc == 0 and len(ad5) == 5 and ad5[4] == 0x49 and ad5[3] == 0xD2 and ad5[2] == 0x23 and ad5[1] == 0x00:
                print(f"probably ISL69127 found at addr: {a:02X}")
                a += 1
                continue

            # TPS53678/9
            rc, ad2 = scan_read_block(bus, a, 0x00, 0xAD, 2)
            if rc == 0 and ad2[0] == 0x01 and ad2[1] == 0x79:
                print(f"probably TPS53679 found at addr: {a:02X}")
                a += 1
                continue
            if rc == 0 and ad2[0] == 0x01 and ad2[1] == 0x78:
                print(f"probably TPS53678 found at addr: {a:02X}")
                a += 1
                continue

            # MP2955A
            rc, bf = scan_read_block(bus, a, 0x00, 0xBF, 2)
            if rc == 0 and bf[0] == 0x55 and bf[1] == 0x25:
                print(f"probably MP2955A found at addr: {a:02X}")
                a += 1
                continue

            # Primarion/PXE1610C 路线
            rc, fd = scan_read_block(bus, a, 0x00, 0xFD, 1)
            if rc == 0 and fd[0] == 0xB3:
                rc, ia = scan_read_block(bus, a, 0x4F, 0x1A, 1)
                if rc == 0 and ia[0] == 0x00:
                    print(f"Primarion family controller found at addr: {a:02X}")
                    rc, x32 = scan_read_block(bus, a, 0x4F, 0x32, 2)
                    if rc == 0 and x32[0] == 0x15 and x32[1] == 0x04:
                        print(f"PXE1610C found at addr: {a:02X}")
                        rc, x82 = scan_read_block(bus, a, 0x50, 0x82, 2)
                        if rc == 0:
                            tmp = (x82[1] << 2) & 0xFF
                            remain = (tmp | (x82[0] >> 6)) & 0xFF
                            print(f" remaining attempts= {remain:02X}")
                        rc, icc = scan_read_block(bus, a, 0x20, 0x73, 2)
                        if rc == 0:
                            print(f" ICC_MAX= {icc[0]:02X}")
        a += 1
    return 0

# ---------- CLI (与原 C# 完全一致) ----------
def _parse_hex7(s: str) -> int:
    try:
        v = int(s, 16)
    except Exception:
        print("Error parsing addr")
        return -1
    if v > 0x7F or v < 0:
        print("addr out of range")
        return -1
    return v

def _parse_hex7_second(s: str) -> int:
    try:
        v = int(s, 16)
    except Exception:
        print("Error parsing addr")
        return -1
    if v > 0x7F or v < 0:
        print("second addr out of range")
        return -1
    return v

def _print_usage():
    print("Usage examples:")
    print("  python3 vrm_pmbus_pi.py -scan 10 77")
    print("  python3 vrm_pmbus_pi.py -PXE1610C 58 [5C]")
    print("  python3 vrm_pmbus_pi.py -MP2955A 60 [61]")
    print("  python3 vrm_pmbus_pi.py -TPS53679 70 [71]")

def main():
    argv = sys.argv[1:]
    if not argv:
        _print_usage()
        return

    cmd = argv[0]
    with SMBus(BUS_ID) as bus:
        if cmd == "-scan":
            if len(argv) < 3:
                _print_usage()
                return
            a1 = _parse_hex7(argv[1])
            if a1 < 0: return
            a2 = _parse_hex7_second(argv[2])
            if a2 < 0: return
            scan_pmbus(bus, a1, a2)
            return

        elif cmd in ("-PXE1610C", "-MP2955A", "-TPS53679", "-TPS53678"):
            if len(argv) < 2:
                _print_usage()
                return
            a1 = _parse_hex7(argv[1])
            if a1 < 0: return
            a2 = None
            if len(argv) >= 3:
                a2 = _parse_hex7_second(argv[2])
                if a2 < 0:
                    return

            # 执行一次或两次
            if cmd == "-PXE1610C":
                pxe1610_set_icc_max(bus, a1)
                if a2 is not None: pxe1610_set_icc_max(bus, a2)

            elif cmd == "-MP2955A":
                mp2955a_set_icc_max(bus, a1)
                if a2 is not None: mp2955a_set_icc_max(bus, a2)

            elif cmd in ("-TPS53679", "-TPS53678"):
                tps53679_set_icc_max(bus, a1)
                if a2 is not None: tps53679_set_icc_max(bus, a2)

            return

        else:
            print("Argument error, expected -scan, -MP2955A, -PXE1610C, -TPS53679 or -TPS53678")
            _print_usage()
            return

if __name__ == "__main__":
    main()