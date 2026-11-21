
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

app = FastAPI(title="Kalkulator Subnet & VLSM")
BASE = Path(__file__).parent


# ---------- fungsi bantu ----------
def _parse_ip(ip: str) -> int:
    """Ubah 'a.b.c.d' menjadi bilangan 32 bit; ValueError bila tidak valid."""
    if not isinstance(ip, str) or ip == "":
        raise ValueError("Alamat IP kosong atau bukan teks.")
    if ip != ip.strip() or any(c.isspace() for c in ip):
        raise ValueError("Alamat IP tidak boleh mengandung spasi.")
    bagian = ip.split(".")
    if len(bagian) != 4:
        raise ValueError("Alamat IP harus terdiri dari 4 oktet.")
    nilai = 0
    for b in bagian:
        if not (b.isascii() and b.isdigit()):
            raise ValueError(f"Oktet '{b}' bukan angka.")
        if len(b) > 1 and b[0] == "0":
            raise ValueError(f"Oktet '{b}' tidak boleh diawali angka nol.")
        if int(b) > 255:
            raise ValueError(f"Oktet {b} melebihi 255.")
        nilai = (nilai << 8) | int(b)
    return nilai


def _to_str(n: int) -> str:
    return ".".join(str((n >> s) & 255) for s in (24, 16, 8, 0))


def _cek_prefix(prefix: int) -> int:
    if isinstance(prefix, bool) or not isinstance(prefix, int) or not 0 <= prefix <= 32:
        raise ValueError("Prefix harus bilangan bulat 0-32.")
    return prefix


def _mask(prefix: int) -> int:
    return (0xFFFFFFFF << (32 - prefix)) & 0xFFFFFFFF if prefix else 0


# ---------- kontrak fungsi (SPEC) ----------
def hitung_subnet(ip: str, prefix: int) -> dict:
    nilai_ip = _parse_ip(ip)
    prefix = _cek_prefix(prefix)

    mask = _mask(prefix)
    network = nilai_ip & mask                  # IP AND subnet mask
    broadcast = network | (~mask & 0xFFFFFFFF)  # semua bit host = 1

    if prefix == 32:      # host tunggal
        first = last = nilai_ip
        hosts, bc = 1, None
    elif prefix == 31:    # point-to-point, RFC 3021
        first, last = network, broadcast
        hosts, bc = 2, None
    else:
        first, last = network + 1, broadcast - 1
        hosts, bc = 2 ** (32 - prefix) - 2, _to_str(broadcast)

    return {
        "mask": _to_str(mask),
        "network": _to_str(network),
        "broadcast": bc,
        "first_host": _to_str(first),
        "last_host": _to_str(last),
        "usable_hosts": hosts,
    }


def alokasi_vlsm(network_cidr: str, kebutuhan_host: list[int]) -> list[dict]:
    if not isinstance(network_cidr, str) or network_cidr.count("/") != 1:
        raise ValueError("Format jaringan harus CIDR, contoh 192.168.1.0/24.")
    ip_teks, pf_teks = network_cidr.split("/")
    if not (pf_teks.isascii() and pf_teks.isdigit()):
        raise ValueError("Prefix jaringan tidak valid.")
    awal, prefix = _parse_ip(ip_teks), _cek_prefix(int(pf_teks))
    if awal & _mask(prefix) != awal:
        raise ValueError(f"{network_cidr} bukan alamat jaringan yang valid.")

    if not isinstance(kebutuhan_host, list) or not kebutuhan_host:
        raise ValueError("Daftar kebutuhan host kosong.")
    for k in kebutuhan_host:
        if isinstance(k, bool) or not isinstance(k, int) or k < 1:
            raise ValueError("Setiap kebutuhan host harus bilangan bulat >= 1.")

    total, offset, hasil = 2 ** (32 - prefix), 0, []
    for k in sorted(kebutuhan_host, reverse=True):  # terbesar dulu
        ukuran = 4                                   # minimal /30
        while ukuran < k + 2:
            ukuran *= 2
        if offset + ukuran > total:
            raise ValueError(f"Blok {network_cidr} tidak cukup untuk seluruh kebutuhan.")
        pf = 32 - (ukuran.bit_length() - 1)
        alamat = _to_str(awal + offset)
        item = {"kebutuhan": k, "network_cidr": f"{alamat}/{pf}"}
        item.update(hitung_subnet(alamat, pf))
        hasil.append(item)
        offset += ukuran
    return hasil


# ---------- API ----------
class VlsmIn(BaseModel):
    network: str
    kebutuhan_host: list[int]


@app.exception_handler(RequestValidationError)
async def _validasi(_: Request, exc: RequestValidationError):
    return JSONResponse(status_code=400, content={"detail": "Body permintaan tidak valid."})


@app.get("/api/subnet")
def api_subnet(ip: str = "", prefix: str = ""):
    try:
        if not (prefix.lstrip("-").isascii() and prefix.lstrip("-").isdigit()):
            raise ValueError("Prefix harus bilangan bulat 0-32.")
        return hitung_subnet(ip, int(prefix))
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": str(e)})


@app.post("/api/vlsm")
def api_vlsm(data: VlsmIn):
    try:
        return alokasi_vlsm(data.network, data.kebutuhan_host)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": str(e)})


@app.get("/")
def index():
    return FileResponse(BASE / "index.html")
