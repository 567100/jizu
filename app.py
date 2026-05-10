from __future__ import annotations

from collections import Counter, deque
from datetime import datetime, timezone
import os
import re
from typing import Deque, Dict, List

from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

MAX_HISTORY = 200
history: Deque[Dict] = deque(maxlen=MAX_HISTORY)


class InputError(ValueError):
    """Invalid user input."""


REGISTER_PATTERN = re.compile(r"^R([0-3])$", re.IGNORECASE)
LABEL_PATTERN = re.compile(r"^[A-Z_][A-Z0-9_]*$")
COMMENT_TOKENS = (";", "#", "//")


def _parse_register(token: str) -> int:
    match = REGISTER_PATTERN.match(token.strip())
    if not match:
        raise InputError(f"寄存器 '{token}' 非法，仅支持 R0~R3。")
    return int(match.group(1))


def _parse_int_token(token: str) -> int:
    text = token.strip()
    if not text:
        raise InputError("立即数或地址不能为空。")
    try:
        return int(text, 0)
    except ValueError as exc:
        raise InputError(f"'{token}' 不是合法数字或标签。") from exc


def _encode_unsigned(value: int, bits: int, name: str) -> int:
    max_val = (1 << bits) - 1
    if not (0 <= value <= max_val):
        raise InputError(f"{name} 超出范围 [0, {max_val}]。")
    return value


def _encode_signed_or_unsigned(value: int, bits: int, name: str) -> int:
    unsigned_max = (1 << bits) - 1
    signed_min = -(1 << (bits - 1))
    if 0 <= value <= unsigned_max:
        return value
    if signed_min <= value < 0:
        return value & unsigned_max
    raise InputError(f"{name} 超出 {bits} 位可编码范围。")


def _strip_comments(line: str) -> str:
    text = line
    for token in COMMENT_TOKENS:
        idx = text.find(token)
        if idx != -1:
            text = text[:idx]
    return text.strip()


def _split_operands(raw: str) -> List[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def _resolve_label_or_number(token: str, labels: Dict[str, int]) -> int:
    key = token.strip().upper()
    if key in labels:
        return labels[key]
    return _parse_int_token(token)


def _pack_common(opcode: int, reg1: int = 0, reg2: int = 0, low8: int = 0) -> int:
    return ((opcode & 0xF) << 12) | ((reg1 & 0x3) << 10) | ((reg2 & 0x3) << 8) | (low8 & 0xFF)


def _pack_jump(opcode: int, addr12: int) -> int:
    return ((opcode & 0xF) << 12) | (addr12 & 0xFFF)


def _normalize_addr_token(token: str) -> str:
    text = token.strip()
    if text.startswith("[") and not text.endswith("]"):
        raise InputError(f"地址写法 '{token}' 缺少右方括号 ]。")
    if not text.startswith("[") and text.endswith("]"):
        raise InputError(f"地址写法 '{token}' 缺少左方括号 [。")
    if text.startswith("[") and text.endswith("]"):
        return text[1:-1].strip()
    return text


def _encode_instruction(mnemonic: str, operands: List[str], labels: Dict[str, int]) -> int:
    op = mnemonic.upper()

    if op == "NOP":
        if operands:
            raise InputError("NOP 不接受操作数。")
        return _pack_common(0x0)
    if op == "MOV":
        if len(operands) != 2:
            raise InputError("MOV 语法: MOV Rd, Rs")
        rd = _parse_register(operands[0])
        rs = _parse_register(operands[1])
        return _pack_common(0x1, rd, rs)
    if op in {"ADD", "SUB", "AND", "OR", "XOR"}:
        if len(operands) != 3:
            raise InputError(f"{op} 语法: {op} Rd, Rs, Rt")
        rd = _parse_register(operands[0])
        rs = _parse_register(operands[1])
        rt = _parse_register(operands[2])
        opcode_map = {"ADD": 0x2, "SUB": 0x3, "AND": 0x4, "OR": 0x5, "XOR": 0x6}
        return _pack_common(opcode_map[op], rd, rs, rt << 6)
    if op == "NOT":
        if len(operands) != 2:
            raise InputError("NOT 语法: NOT Rd, Rs")
        rd = _parse_register(operands[0])
        rs = _parse_register(operands[1])
        return _pack_common(0x7, rd, rs)
    if op == "LDI":
        if len(operands) != 2:
            raise InputError("LDI 语法: LDI Rd, Imm8")
        rd = _parse_register(operands[0])
        imm_raw = _resolve_label_or_number(operands[1], labels)
        imm8 = _encode_signed_or_unsigned(imm_raw, 8, "立即数")
        return _pack_common(0x8, rd, 0, imm8)
    if op == "LD":
        if len(operands) != 2:
            raise InputError("LD 语法: LD Rd, [Addr8]")
        rd = _parse_register(operands[0])
        addr_raw = _resolve_label_or_number(_normalize_addr_token(operands[1]), labels)
        addr8 = _encode_unsigned(addr_raw, 8, "地址")
        return _pack_common(0x9, rd, 0, addr8)
    if op == "ST":
        if len(operands) != 2:
            raise InputError("ST 语法: ST Rs, [Addr8]")
        rs = _parse_register(operands[0])
        addr_raw = _resolve_label_or_number(_normalize_addr_token(operands[1]), labels)
        addr8 = _encode_unsigned(addr_raw, 8, "地址")
        return _pack_common(0xA, rs, 0, addr8)
    if op == "JMP":
        if len(operands) != 1:
            raise InputError("JMP 语法: JMP Addr12")
        addr_raw = _resolve_label_or_number(operands[0], labels)
        addr12 = _encode_unsigned(addr_raw, 12, "跳转地址")
        return _pack_jump(0xB, addr12)
    if op == "JZ":
        if len(operands) != 2:
            raise InputError("JZ 语法: JZ Rd, Addr8")
        rd = _parse_register(operands[0])
        addr_raw = _resolve_label_or_number(operands[1], labels)
        addr8 = _encode_unsigned(addr_raw, 8, "跳转地址")
        return _pack_common(0xC, rd, 0, addr8)
    if op == "JNZ":
        if len(operands) != 2:
            raise InputError("JNZ 语法: JNZ Rd, Addr8")
        rd = _parse_register(operands[0])
        addr_raw = _resolve_label_or_number(operands[1], labels)
        addr8 = _encode_unsigned(addr_raw, 8, "跳转地址")
        return _pack_common(0xD, rd, 0, addr8)
    if op == "HALT":
        if operands:
            raise InputError("HALT 不接受操作数。")
        return _pack_common(0xF)

    raise InputError(f"不支持的指令: {mnemonic}")


def assemble_program(source: str) -> Dict:
    if source is None or not source.strip():
        raise InputError("汇编源码不能为空。")

    lines = source.splitlines()
    labels: Dict[str, int] = {}
    instructions = []
    address = 0

    for idx, raw in enumerate(lines, start=1):
        stripped = _strip_comments(raw)
        if not stripped:
            continue

        work = stripped
        while ":" in work:
            left, right = work.split(":", 1)
            label = left.strip().upper()
            if not label:
                raise InputError(f"第 {idx} 行标签为空。")
            if not LABEL_PATTERN.match(label):
                raise InputError(
                    f"第 {idx} 行标签 '{label}' 非法。标签必须以字母或下划线开头，且仅可包含字母、数字、下划线。"
                )
            if label in labels:
                raise InputError(f"第 {idx} 行标签 '{label}' 重复定义。")
            labels[label] = address
            work = right.strip()
            if not work:
                break

        if work:
            instructions.append({"line_no": idx, "source": work, "address": address})
            address += 1

    if not instructions:
        raise InputError("没有可汇编的指令。")

    machine_lines = []
    for row in instructions:
        src = row["source"].strip()
        parts = src.split(None, 1)
        mnemonic = parts[0]
        operands = _split_operands(parts[1]) if len(parts) > 1 else []
        try:
            code = _encode_instruction(mnemonic, operands, labels)
        except InputError as exc:
            raise InputError(f"第 {row['line_no']} 行: {exc}") from exc

        machine_lines.append(
            {
                "line_no": row["line_no"],
                "address": row["address"],
                "source": src,
                "binary": format(code & 0xFFFF, "016b"),
                "hex": f"0x{code & 0xFFFF:04X}",
            }
        )

    return {
        "word_length": 16,
        "instruction_count": len(machine_lines),
        "label_count": len(labels),
        "labels": labels,
        "lines": machine_lines,
    }


def parse_number(raw: str, base: int) -> int:
    if raw is None:
        raise InputError("输入不能为空。")

    text = raw.strip().lower()
    if not text:
        raise InputError("输入不能为空。")

    # Allow optional base prefixes.
    prefix_map = {2: "0b", 8: "0o", 16: "0x"}
    if base in prefix_map and text.startswith(prefix_map[base]):
        text = text[2:]

    try:
        return int(text, base)
    except ValueError as exc:
        raise InputError(f"'{raw}' 不是合法的 {base} 进制数字。") from exc


def to_base(value: int, base: int) -> str:
    if base == 2:
        return bin(value)
    if base == 8:
        return oct(value)
    if base == 10:
        return str(value)
    if base == 16:
        return hex(value)
    raise InputError("不支持的进制。")


def _mask(width: int) -> int:
    return (1 << width) - 1


def validate_width(width: int) -> int:
    valid = {4, 8, 16, 32}
    if width not in valid:
        raise InputError(f"仅支持位宽 {sorted(valid)}。")
    return width


def normalize_to_signed(value: int, width: int) -> int:
    value &= _mask(width)
    sign_bit = 1 << (width - 1)
    return value - (1 << width) if value & sign_bit else value


def compute_codes(value: int, width: int) -> Dict[str, str]:
    if width < 2:
        raise InputError("位宽必须至少为 2。")

    max_pos = (1 << (width - 1)) - 1
    min_neg = -(1 << (width - 1))
    if value < min_neg or value > max_pos:
        raise InputError(f"值 {value} 超出 {width} 位有符号整数范围 [{min_neg}, {max_pos}]。")

    if value >= 0:
        sign_magnitude = format(value, f"0{width}b")
        ones_comp = sign_magnitude
        twos_comp = sign_magnitude
    else:
        mag_bits = format(abs(value), f"0{width - 1}b")
        sign_magnitude = "1" + mag_bits[-(width - 1) :]

        positive_bits = format(abs(value), f"0{width}b")
        ones_val = _mask(width) ^ int(positive_bits, 2)
        ones_comp = format(ones_val, f"0{width}b")

        twos_val = (ones_val + 1) & _mask(width)
        twos_comp = format(twos_val, f"0{width}b")

    bias = 1 << (width - 1)
    biased_val = value + bias
    biased_code = format(biased_val & _mask(width), f"0{width}b")

    return {
        "原码": sign_magnitude,
        "反码": ones_comp,
        "补码": twos_comp,
        "移码": biased_code,
    }


def infer_width(values: List[int], requested: int | None = None) -> int:
    if requested:
        return validate_width(requested)

    max_abs = max(abs(v) for v in values) if values else 0
    needed = max_abs.bit_length() + 1
    if needed <= 8:
        return 8
    if needed <= 16:
        return 16
    return 32


def cla_add(a: int, b: int, width: int) -> Dict:
    mask = _mask(width)
    a_u = a & mask
    b_u = b & mask

    bits = []
    p_bits: List[int] = []
    g_bits: List[int] = []

    for i in range(width):
        ai = (a_u >> i) & 1
        bi = (b_u >> i) & 1
        p = ai ^ bi
        g = ai & bi
        p_bits.append(p)
        g_bits.append(g)
        bits.append({"index": i, "a": ai, "b": bi, "p": p, "g": g})

    carries = [0] * (width + 1)
    for i in range(width):
        carries[i + 1] = g_bits[i] | (p_bits[i] & carries[i])

    sum_bits = [p_bits[i] ^ carries[i] for i in range(width)]
    sum_unsigned = sum(bit << i for i, bit in enumerate(sum_bits))
    max_val = (1 << (width - 1)) - 1
    sum_signed = sum_unsigned - (1 << width) if sum_unsigned > max_val else sum_unsigned
    overflow = carries[width] ^ carries[width - 1]

    return {
        "a_binary": format(a_u, f"0{width}b"),
        "b_binary": format(b_u, f"0{width}b"),
        "sum_binary": format(sum_unsigned, f"0{width}b"),
        "sum_signed": sum_signed,
        "carry_in_msb": carries[width - 1],
        "carry_out": carries[width],
        "overflow": bool(overflow),
        "bit_rows": bits,
        "carry_chain": carries,
    }


def simulate_alu8(a: int, b: int, func: int, width: int, cin: int, phase: int) -> Dict:
    mask = _mask(width)
    a_u = a & mask
    b_u = b & mask

    operations = {
        0: ("ADD", a_u + b_u + cin),
        1: ("SUB", a_u + ((~b_u) & mask) + 1),
        2: ("AND", a_u & b_u),
        3: ("OR", a_u | b_u),
        4: ("XOR", a_u ^ b_u),
        5: ("NOT A", (~a_u) & mask),
        6: ("PASS A", a_u),
        7: ("INC A", a_u + 1),
    }
    if func not in operations:
        raise InputError("功能码仅支持 0~7。")

    op_name, raw_result = operations[func]
    result_u = raw_result & mask
    carry_out = 1 if raw_result > mask else 0

    a_signed = normalize_to_signed(a_u, width)
    b_signed = normalize_to_signed(b_u, width)
    result_signed = normalize_to_signed(result_u, width)

    overflow = False
    if func in {0, 1, 7}:
        if func == 0:
            math_result = a_signed + b_signed + cin
        elif func == 1:
            math_result = a_signed - b_signed
        else:
            math_result = a_signed + 1
        min_val, max_val = -(1 << (width - 1)), (1 << (width - 1)) - 1
        overflow = not (min_val <= math_result <= max_val)

    phase = max(0, min(3, phase))
    phases = [
        "T0 取数：锁存输入 A/B 与控制位。",
        "T1 运算：组合逻辑产生中间结果。",
        "T2 校验：更新进位/溢出/零标志。",
        "T3 输出：结果写回总线并显示。",
    ]

    return {
        "op_name": op_name,
        "func": func,
        "phase": phase,
        "phase_desc": phases[phase],
        "a_binary": format(a_u, f"0{width}b"),
        "b_binary": format(b_u, f"0{width}b"),
        "result_binary": format(result_u, f"0{width}b"),
        "a_signed": a_signed,
        "b_signed": b_signed,
        "result_signed": result_signed,
        "carry_out": carry_out,
        "overflow": overflow,
        "zero": result_u == 0,
        "negative": ((result_u >> (width - 1)) & 1) == 1,
        "control_word": f"F={func:03b}, CIN={cin}, T={phase:02b}",
    }


def merge_sort_trace(values: List[int]) -> Dict:
    if not values:
        raise InputError("待排序数据不能为空。")
    if len(values) > 64:
        raise InputError("单次最多支持 64 个数据，以保证可视化清晰。")

    steps: List[Dict] = []

    def walk(arr: List[int], depth: int) -> List[int]:
        if len(arr) <= 1:
            steps.append({"phase": "base", "depth": depth, "segment": arr[:]})
            return arr[:]
        mid = len(arr) // 2
        left = arr[:mid]
        right = arr[mid:]
        steps.append({"phase": "split", "depth": depth, "source": arr[:], "left": left[:], "right": right[:]})
        left_sorted = walk(left, depth + 1)
        right_sorted = walk(right, depth + 1)

        merged: List[int] = []
        i, j = 0, 0
        while i < len(left_sorted) and j < len(right_sorted):
            if left_sorted[i] <= right_sorted[j]:
                merged.append(left_sorted[i])
                i += 1
            else:
                merged.append(right_sorted[j])
                j += 1
        merged.extend(left_sorted[i:])
        merged.extend(right_sorted[j:])
        steps.append({"phase": "merge", "depth": depth, "left": left_sorted[:], "right": right_sorted[:], "result": merged[:]})
        return merged

    sorted_values = walk(values[:], 0)
    return {"input": values, "steps": steps, "sorted": sorted_values}


def add_history(item_type: str, payload: Dict) -> None:
    history.appendleft(
        {
            "type": item_type,
            "time": datetime.now(timezone.utc).isoformat(),
            **payload,
        }
    )


@app.route("/")
def index():
    return converter_page()


@app.route("/converter")
def converter_page():
    return render_template("index.html", page="converter")


@app.route("/arithmetic")
def arithmetic_page():
    return render_template("index.html", page="arithmetic")


@app.route("/simulator")
def simulator_page():
    return render_template("index.html", page="simulator")


@app.route("/admin")
def admin_page():
    return render_template("index.html", page="admin")


@app.route("/guide")
def guide_page():
    return render_template("index.html", page="guide")


@app.route("/instruction")
def instruction_page():
    return render_template("index.html", page="instruction")


@app.route("/merge-sort")
def merge_sort_page():
    return render_template("index.html", page="merge_sort")


@app.post("/api/convert")
def api_convert():
    data = request.get_json(silent=True) or {}
    try:
        a = parse_number(str(data.get("a", "")), int(data.get("a_base", 10)))
        b = parse_number(str(data.get("b", "")), int(data.get("b_base", 10)))
        out_base = int(data.get("out_base", 10))
        width = infer_width([a, b], int(data["width"]) if data.get("width") else None)

        result = {
            "a_decimal": a,
            "b_decimal": b,
            "sum": to_base(a + b, out_base),
            "difference": to_base(a - b, out_base),
            "product": to_base(a * b, out_base),
            "codes_a": compute_codes(a, width),
            "codes_b": compute_codes(b, width),
            "width": width,
        }

        add_history(
            "convert",
            {
                "label": f"转换: {data.get('a')}({data.get('a_base')}) 与 {data.get('b')}({data.get('b_base')})",
                "detail": f"sum={result['sum']}, diff={result['difference']}",
                "a_base": int(data.get("a_base", 10)),
                "b_base": int(data.get("b_base", 10)),
            },
        )
        return jsonify({"ok": True, "result": result})
    except InputError:
        return jsonify({"ok": False, "error": "输入不合法，请检查格式与范围。"}), 400
    except ValueError:
        return jsonify({"ok": False, "error": "参数格式错误。"}), 400


@app.post("/api/calc")
def api_calc():
    data = request.get_json(silent=True) or {}
    try:
        a = parse_number(str(data.get("a", "")), int(data.get("base", 10)))
        b = parse_number(str(data.get("b", "")), int(data.get("base", 10)))
        op = data.get("op", "+")
        width = validate_width(int(data.get("width", 8)))

        if op not in {"+", "-"}:
            raise InputError("仅支持 + 或 - 运算。")

        math_result = a + b if op == "+" else a - b
        min_val, max_val = -(1 << (width - 1)), (1 << (width - 1)) - 1
        overflow = not (min_val <= math_result <= max_val)
        wrapped = ((math_result + (1 << width)) & _mask(width))

        payload = {
            "a": a,
            "b": b,
            "op": op,
            "math_result": math_result,
            "width": width,
            "range": [min_val, max_val],
            "overflow": overflow,
            "wrapped_binary": format(wrapped, f"0{width}b"),
            "wrapped_signed": wrapped - (1 << width) if wrapped > max_val else wrapped,
        }
        if op == "+":
            payload["cla"] = cla_add(a, b, width)

        add_history(
            "arithmetic",
            {
                "label": f"运算: {a} {op} {b}",
                "detail": f"result={math_result}, overflow={overflow}",
                "op": op,
            },
        )
        return jsonify({"ok": True, "result": payload})
    except InputError:
        return jsonify({"ok": False, "error": "输入不合法，请检查格式与范围。"}), 400
    except ValueError:
        return jsonify({"ok": False, "error": "参数格式错误。"}), 400


@app.post("/api/simulate")
def api_simulate():
    data = request.get_json(silent=True) or {}
    try:
        width = validate_width(int(data.get("width", 8)))
        base = int(data.get("base", 2))
        a = parse_number(str(data.get("a", "0")), base)
        b = parse_number(str(data.get("b", "0")), base)
        func = int(data.get("func", 0))
        cin = 1 if data.get("cin") else 0
        phase = int(data.get("phase", 0))

        result = simulate_alu8(a, b, func, width, cin, phase)

        add_history(
            "simulator",
            {
                "label": f"仿真: {result['op_name']} (F={func:03b})",
                "detail": f"A={result['a_binary']} B={result['b_binary']} => Y={result['result_binary']}",
                "func": func,
            },
        )
        return jsonify({"ok": True, "result": result})
    except InputError:
        return jsonify({"ok": False, "error": "输入不合法，请检查格式与范围。"}), 400
    except ValueError:
        return jsonify({"ok": False, "error": "参数格式错误。"}), 400


@app.post("/api/assemble")
def api_assemble():
    data = request.get_json(silent=True) or {}
    try:
        source = str(data.get("source", ""))
        result = assemble_program(source)
        add_history(
            "instruction",
            {
                "label": f"汇编: {result['instruction_count']} 条指令",
                "detail": f"机器字长={result['word_length']} 位，标签={result['label_count']} 个",
            },
        )
        return jsonify({"ok": True, "result": result})
    except InputError:
        return jsonify({"ok": False, "error": "输入不合法，请检查指令语法、寄存器与地址范围。"}), 400
    except ValueError:
        return jsonify({"ok": False, "error": "参数格式错误。"}), 400


@app.post("/api/merge-sort")
def api_merge_sort():
    data = request.get_json(silent=True) or {}
    try:
        base = int(data.get("base", 10))
        if base not in {2, 8, 10, 16}:
            raise InputError("仅支持二/八/十/十六进制输入。")
        raw_items = data.get("items", [])
        if not isinstance(raw_items, list):
            raise InputError("待排序数据格式错误。")
        values = [parse_number(str(item), base) for item in raw_items]
        result = merge_sort_trace(values)
        add_history(
            "merge_sort",
            {
                "label": f"归并排序: {len(values)} 项（{base}进制）",
                "detail": f"结果首项={result['sorted'][0]}，末项={result['sorted'][-1]}",
                "base": base,
            },
        )
        return jsonify({"ok": True, "result": result})
    except InputError:
        return jsonify({"ok": False, "error": "输入不合法，请检查进制与数据格式。"}), 400
    except ValueError:
        return jsonify({"ok": False, "error": "参数格式错误。"}), 400


@app.get("/api/history")
def api_history():
    return jsonify({"ok": True, "items": list(history)})


@app.get("/api/stats")
def api_stats():
    type_counter = Counter(item["type"] for item in history)
    op_counter = Counter(item.get("op", "N/A") for item in history if item["type"] == "arithmetic")
    base_counter = Counter()
    for item in history:
        if item["type"] == "convert":
            base_counter[str(item.get("a_base", "?"))] += 1
            base_counter[str(item.get("b_base", "?"))] += 1
        if item["type"] == "merge_sort":
            base_counter[str(item.get("base", "?"))] += 1

    return jsonify(
        {
            "ok": True,
            "stats": {
                "type_counter": type_counter,
                "op_counter": op_counter,
                "base_counter": base_counter,
                "total": len(history),
            },
        }
    )


if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG", "").lower() in {"1", "true", "yes"})
