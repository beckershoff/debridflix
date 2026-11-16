"""Minimal QR encoder (byte mode, error level L, versions 1-5) and PNG writer. Stdlib only."""
import struct
import zlib

DATA_CODEWORDS = {1: 19, 2: 34, 3: 55, 4: 80, 5: 108}
EC_CODEWORDS = {1: 7, 2: 10, 3: 15, 4: 20, 5: 26}


def _gf_tables():
    exp, log = [0] * 512, [0] * 256
    x = 1
    for i in range(255):
        exp[i], log[x] = x, i
        x <<= 1
        if x & 0x100:
            x ^= 0x11D
    for i in range(255, 512):
        exp[i] = exp[i - 255]
    return exp, log


_EXP, _LOG = _gf_tables()


def _mul(a, b):
    return 0 if not a or not b else _EXP[_LOG[a] + _LOG[b]]


def _reed_solomon(data, count):
    gen = [1]
    for i in range(count):
        gen = _poly_mul(gen, [1, _EXP[i]])
    rem = [0] * count
    for byte in data:
        factor = byte ^ rem[0]
        rem = rem[1:] + [0]
        for j in range(count):
            rem[j] ^= _mul(gen[j + 1], factor)
    return rem


def _poly_mul(a, b):
    out = [0] * (len(a) + len(b) - 1)
    for i, x in enumerate(a):
        for j, y in enumerate(b):
            out[i + j] ^= _mul(x, y)
    return out


def encode(text):
    """Returns the QR code as a list of rows of booleans (True = dark)."""
    payload = text.encode("utf-8")
    version = next((v for v in sorted(DATA_CODEWORDS) if len(payload) <= DATA_CODEWORDS[v] - 2), None)
    if version is None:
        raise ValueError("Text too long for the built-in QR encoder")
    capacity = DATA_CODEWORDS[version]
    bits = [0, 1, 0, 0] + [(len(payload) >> i) & 1 for i in range(7, -1, -1)]
    for byte in payload:
        bits += [(byte >> i) & 1 for i in range(7, -1, -1)]
    bits += [0] * min(4, capacity * 8 - len(bits))
    bits += [0] * (-len(bits) % 8)
    data = [int("".join(str(b) for b in bits[i:i + 8]), 2) for i in range(0, len(bits), 8)]
    pad = (0xEC, 0x11)
    data += [pad[i % 2] for i in range(capacity - len(data))]
    codewords = data + _reed_solomon(data, EC_CODEWORDS[version])

    size = 17 + 4 * version
    dark = [[False] * size for _ in range(size)]
    fixed = [[False] * size for _ in range(size)]

    def put(x, y, value):
        if 0 <= x < size and 0 <= y < size:
            dark[y][x] = bool(value)
            fixed[y][x] = True

    for i in range(size):  # timing
        put(6, i, i % 2 == 0)
        put(i, 6, i % 2 == 0)
    for cx, cy in ((3, 3), (size - 4, 3), (3, size - 4)):  # finders with separators
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                dist = max(abs(dx), abs(dy))
                put(cx + dx, cy + dy, dist not in (2, 4))
    if version >= 2:  # single alignment pattern
        centre = 4 * version + 10
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                put(centre + dx, centre + dy, max(abs(dx), abs(dy)) != 1)

    def format_bits(mask):
        value = (1 << 3) | mask  # level L
        rem = value
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        word = ((value << 10) | rem) ^ 0x5412
        bit = lambda i: (word >> i) & 1
        for i in range(6):
            put(8, i, bit(i))
        put(8, 7, bit(6))
        put(8, 8, bit(7))
        put(7, 8, bit(8))
        for i in range(9, 15):
            put(14 - i, 8, bit(i))
        for i in range(8):
            put(size - 1 - i, 8, bit(i))
        for i in range(8, 15):
            put(8, size - 15 + i, bit(i))
        put(8, size - 8, True)

    format_bits(0)  # reserve the format area before placing data
    index, total = 0, len(codewords) * 8
    right = size - 1
    while right >= 1:
        if right == 6:
            right = 5
        for vert in range(size):
            for j in range(2):
                x = right - j
                upward = ((right + 1) & 2) == 0
                y = size - 1 - vert if upward else vert
                if not fixed[y][x] and index < total:
                    dark[y][x] = bool((codewords[index >> 3] >> (7 - (index & 7))) & 1)
                    index += 1
        right -= 2
    for y in range(size):  # mask pattern 0
        for x in range(size):
            if not fixed[y][x] and (x + y) % 2 == 0:
                dark[y][x] = not dark[y][x]
    return dark


def png(matrix, size=480, quiet=4):
    """Renders the matrix centred on a white square of size x size pixels. Returns PNG bytes."""
    modules = len(matrix) + 2 * quiet
    scale = max(1, size // modules)
    offset = (size - scale * modules) // 2 + quiet * scale
    rows = []
    for py in range(size):
        my = (py - offset) // scale
        row = bytearray(b"\xff" * (size * 3))
        if 0 <= my < len(matrix):
            for mx, value in enumerate(matrix[my]):
                if value:
                    start = (offset + mx * scale) * 3
                    row[start:start + scale * 3] = b"\x00" * (scale * 3)
        rows.append(b"\x00" + bytes(row))

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b""))
