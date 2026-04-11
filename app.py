from __future__ import annotations

from collections import Counter, deque
from datetime import datetime, timezone
from typing import Deque, Dict, List

from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

MAX_HISTORY = 200
history: Deque[Dict] = deque(maxlen=MAX_HISTORY)


class InputError(ValueError):
    """Invalid user input."""


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


@app.route("/admin")
def admin_page():
    return render_template("index.html", page="admin")


@app.route("/guide")
def guide_page():
    return render_template("index.html", page="guide")


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
    except (InputError, ValueError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


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
    except (InputError, ValueError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


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
    app.run(debug=True)
