#!/usr/bin/env python3
# control_inlet_valve.py
# 控制 ICSSIM 水箱入口阀门（tank_input_valve_mode）
# Mode: 1 = 强制关闭, 2 = 强制开启, 3 = 自动（PLC 控制）

from pyModbusTCP.client import ModbusClient

# ICSSIM PLC1 地址（LOCAL 模式）
PLC1_HOST = "127.0.0.1"
PLC1_PORT = 5502

# TAG 定义（来自 ICSSIM Configs.py）
TAG_TANK_INPUT_VALVE_MODE   = {"id": 1, "desc": "入口阀模式 (1=关, 2=开, 3=自动)"}
TAG_TANK_INPUT_VALVE_STATUS = {"id": 0, "desc": "入口阀状态 (只读)"}
TAG_TANK_LEVEL_VALUE        = {"id": 2, "desc": "水箱液位 (只读, 单位: L)"}

WORD_NUM = 2
PRECISION = 4
SCALE = 10**PRECISION  # ICSSIM 用 2 个寄存器保存值，值 = 实际值 × 10000
REGISTER_BASE = 2**16


def get_register_address(tag_id: int) -> int:
    return tag_id * WORD_NUM


def decode_registers(regs: list[int] | None) -> float | None:
    if regs is None or len(regs) != WORD_NUM:
        return None

    result = 0
    base_holder = 1
    for word in regs:
        result *= base_holder
        result += word
        base_holder *= REGISTER_BASE
    return result / SCALE


def encode_registers(value: float) -> list[int]:
    number = int(value * SCALE)
    if number < 0:
        raise ValueError("ICSSIM Modbus 编码不支持负数")

    regs = []
    while number:
        regs.append(number % REGISTER_BASE)
        number = int(number / REGISTER_BASE)

    while len(regs) < WORD_NUM:
        regs.append(0)

    regs.reverse()
    return regs


def read_register(client: ModbusClient, reg_id: int) -> float | None:
    regs = client.read_holding_registers(get_register_address(reg_id), WORD_NUM)
    return decode_registers(regs)


def write_register(client: ModbusClient, reg_id: int, value: float) -> bool:
    return client.write_multiple_registers(get_register_address(reg_id), encode_registers(value))


def print_status(client: ModbusClient):
    level  = read_register(client, TAG_TANK_LEVEL_VALUE["id"])
    status = read_register(client, TAG_TANK_INPUT_VALVE_STATUS["id"])
    mode   = read_register(client, TAG_TANK_INPUT_VALVE_MODE["id"])

    mode_str = {1.0: "强制关闭", 2.0: "强制开启", 3.0: "自动"}.get(mode, f"未知({mode})")
    status_str = "开" if status else "关"

    print(f"\n  水箱液位:   {level:.2f} L" if level is not None else "\n  水箱液位:   读取失败")
    print(f"  入口阀状态: {status_str}")
    print(f"  入口阀模式: {mode_str}\n")


def main():
    client = ModbusClient(host=PLC1_HOST, port=PLC1_PORT, auto_open=True, auto_close=False)

    if not client.open():
        print(f"[错误] 无法连接到 PLC1 ({PLC1_HOST}:{PLC1_PORT})")
        print("请确认 ICSSIM 已启动（python3 start.py）")
        return

    print(f"[已连接] PLC1 @ {PLC1_HOST}:{PLC1_PORT}")
    print("=" * 40)

    while True:
        print("当前状态：")
        print_status(client)

        print("操作选项：")
        print("  1 — 强制关闭入口阀")
        print("  2 — 强制开启入口阀")
        print("  3 — 恢复自动模式（PLC 控制）")
        print("  s — 刷新状态")
        print("  q — 退出")

        choice = input("请选择 > ").strip().lower()

        if choice == "q":
            print("退出。")
            break
        elif choice == "s":
            continue
        elif choice in ("1", "2", "3"):
            mode = int(choice)
            success = write_register(client, TAG_TANK_INPUT_VALVE_MODE["id"], mode)
            if success:
                mode_str = {1: "强制关闭", 2: "强制开启", 3: "自动"}.get(mode)
                print(f"[成功] 入口阀已设置为：{mode_str}")
            else:
                print("[失败] 写入失败，请检查连接")
        else:
            print("[提示] 无效输入，请输入 1 / 2 / 3 / s / q")

    client.close()


if __name__ == "__main__":
    main()
