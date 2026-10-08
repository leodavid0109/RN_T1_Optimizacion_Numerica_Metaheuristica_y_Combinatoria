#!/usr/bin/env python3
"""Bitácora de alucinaciones: formulario local para registrar hallazgos.

Uso (desde la raíz del repositorio):

    python tools/bitacora/server.py            # abre http://127.0.0.1:8765
    python tools/bitacora/server.py --port 9000 --dir docs/alucinaciones

Cada hallazgo se guarda como un archivo JSON propio en <dir>/data/<id>.json
y el reporte <dir>/alucinaciones.md se regenera en cada cambio. Como cada
hallazgo es un archivo distinto, dos personas que registran hallazgos en
paralelo no generan conflictos de Git. Solo usa la biblioteca estándar.
"""
import argparse
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent

CATEGORIAS = {
    "mate": "Matemáticas",
    "codigo": "Código",
    "datos": "Datos del mundo real",
    "biblio": "Bibliografía",
    "conceptos": "Conceptos",
}
ESTADOS = {
    "pendiente": "Por verificar",
    "confirmado": "Confirmado",
    "descartado": "Descartado (la IA acertó)",
}
CAMPOS = {  # campo -> longitud máxima
    "titulo": 140, "categoria": 20, "herramienta": 120, "referencia": 160,
    "prompt": 40000, "respuesta": 40000, "sospecha": 8000, "evidencia": 16000,
    "correccion": 8000, "leccion": 8000, "estado": 20,
}
ID_RE = re.compile(r"^[0-9a-f]{6}$")
MAX_BODY = 512 * 1024
LOCK = threading.Lock()


def autor_por_defecto():
    """Nombre de quien registra: git config user.name, o el usuario del sistema."""
    try:
        out = subprocess.run(["git", "config", "user.name"], capture_output=True,
                             text=True, timeout=3).stdout.strip()
        if out:
            return out[:80]
    except (OSError, subprocess.SubprocessError):
        pass
    return (os.environ.get("USER") or os.environ.get("USERNAME") or "Integrante")[:80]


def validar(d):
    """Mismas reglas que la interfaz. Devuelve un mensaje de error o ''."""
    if not d["titulo"]:
        return "Escribe un título corto."
    if d["categoria"] not in CATEGORIAS:
        return "Categoría no válida."
    if d["estado"] not in ESTADOS:
        return "Estado no válido."
    if not d["prompt"]:
        return "Pega el prompt literal: es lo primero que se registra."
    if not d["respuesta"]:
        return "Pega la respuesta de la IA tal cual."
    if d["estado"] == "confirmado":
        falta = [n for k, n in (("sospecha", "cómo sospechaste"), ("evidencia", "la evidencia"),
                                ("correccion", "la corrección"), ("leccion", "la lección")) if not d[k]]
        if falta:
            return ("Un hallazgo confirmado necesita " + ", ".join(falta) +
                    ". Si aún no la tienes, déjalo en «Por verificar».")
    if d["estado"] == "descartado" and not d["evidencia"]:
        return "Describe qué verificaste y qué resultó correcto."
    return ""


class Almacen:
    def __init__(self, base: Path):
        self.base = base
        self.datos = base / "data"
        self.datos.mkdir(parents=True, exist_ok=True)

    def _ruta(self, hid):
        if not ID_RE.match(hid):
            raise ValueError("id no válido")
        return self.datos / f"{hid}.json"

    def listar(self):
        items = []
        for p in sorted(self.datos.glob("*.json")):
            try:
                items.append(json.loads(p.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue  # un archivo dañado no tumba la lista
        items.sort(key=lambda i: (i.get("createdAt", 0), i.get("id", "")))
        for n, i in enumerate(items, 1):
            i["codigo"] = f"H-{n:02d}"
        return items

    def _escribir(self, ruta: Path, texto: str):
        fd, tmp = tempfile.mkstemp(dir=ruta.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                f.write(texto)
            os.replace(tmp, ruta)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def guardar(self, hid, d, autor):
        ahora = int(time.time() * 1000)
        if hid is None:
            hid = secrets.token_hex(3)
            while self._ruta(hid).exists():
                hid = secrets.token_hex(3)
            doc = {"id": hid, "autor": autor, "createdAt": ahora}
        else:
            ruta = self._ruta(hid)
            if not ruta.exists():
                raise FileNotFoundError(hid)
            doc = json.loads(ruta.read_text(encoding="utf-8"))
        doc.update(d)
        doc["updatedAt"] = ahora
        self._escribir(self._ruta(hid), json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
        self.exportar()
        return hid

    def borrar(self, hid):
        ruta = self._ruta(hid)
        if not ruta.exists():
            raise FileNotFoundError(hid)
        ruta.unlink()
        self.exportar()

    def exportar(self):
        ruta = self.base / "alucinaciones.md"
        self._escribir(ruta, a_markdown(self.listar()))
        return ruta


def fecha(ms):
    try:
        return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return ""


def a_markdown(items):
    conf = [i for i in items if i.get("estado") == "confirmado"]
    cats = sorted({CATEGORIAS.get(i.get("categoria"), "?") for i in conf})
    out = ["# Cacería de la alucinación", "",
           "Generado por `tools/bitacora/server.py`. No editar a mano: edita desde la herramienta.", "",
           f"- Hallazgos confirmados: {len(conf)} (mínimo 5)",
           f"- Categorías cubiertas: {len(cats)} (mínimo 3){': ' + ', '.join(cats) if cats else ''}",
           f"- Por verificar: {sum(1 for i in items if i.get('estado') == 'pendiente')}",
           f"- Verificaciones sin error: {sum(1 for i in items if i.get('estado') == 'descartado')}", ""]
    for i in items:
        out += [f"## {i['codigo']} · {CATEGORIAS.get(i.get('categoria'), '?')} · {fecha(i.get('createdAt'))}",
                f"**{i.get('titulo', '')}**", "",
                f"Referencia estable: `{i['id']}` · Estado: {ESTADOS.get(i.get('estado'), '?')} · "
                f"Registró: {i.get('autor', '—')}",
                f"Herramienta/modelo: {i.get('herramienta') or '—'} · Archivo afectado: {i.get('referencia') or '—'}", "",
                "1. Prompt (literal):", "", "~~~~", i.get("prompt", ""), "~~~~", "",
                "2. Respuesta de la IA (fragmento relevante, literal):", "", "~~~~", i.get("respuesta", ""), "~~~~", "",
                "3. Por qué sospeché:", "", i.get("sospecha") or "—", "",
                "4. Evidencia (derivación, experimento, fuente primaria con fecha de consulta):", "",
                i.get("evidencia") or "—", "",
                "5. Corrección (commit que la aplica):", "", i.get("correccion") or "—", "",
                "6. Lección / verificación que lo habría evitado:", "", i.get("leccion") or "—", ""]
    return "\n".join(out)


def limpiar(cuerpo):
    if not isinstance(cuerpo, dict):
        raise ValueError("Cuerpo no válido.")
    d = {}
    for k, mx in CAMPOS.items():
        v = cuerpo.get(k, "")
        if not isinstance(v, str):
            raise ValueError(f"El campo {k} debe ser texto.")
        v = v.strip()
        if len(v) > mx:
            raise ValueError(f"El campo {k} supera {mx} caracteres.")
        d[k] = v
    return d


class Manejador(BaseHTTPRequestHandler):
    almacen: Almacen = None
    autor: str = ""
    puerto: int = 0
    server_version = "Bitacora/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("  %s\n" % (fmt % args))

    # Defensas: solo local, y las escrituras exigen una cabecera propia
    # (obliga a preflight CORS, que este servidor nunca aprueba).
    def _host_ok(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost")

    def _responder(self, codigo, cuerpo=b"", tipo="application/json; charset=utf-8"):
        if isinstance(cuerpo, (dict, list)):
            cuerpo = json.dumps(cuerpo, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(cuerpo)

    def _error(self, codigo, msg):
        self._responder(codigo, {"error": msg})

    def _leer_json(self):
        if self.headers.get("X-Bitacora") != "1":
            raise PermissionError("Falta la cabecera de seguridad.")
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise ValueError("Cuerpo demasiado grande.")
        return json.loads(self.rfile.read(n).decode("utf-8") or "null")

    def do_GET(self):
        if not self._host_ok():
            return self._error(HTTPStatus.FORBIDDEN, "Host no permitido.")
        ruta = self.path.split("?")[0]
        if ruta in ("/", "/index.html"):
            html = (HERE / "index.html").read_bytes()
            return self._responder(HTTPStatus.OK, html, "text/html; charset=utf-8")
        if ruta == "/api/hallazgos":
            with LOCK:
                return self._responder(HTTPStatus.OK, {"autor": self.autor, "items": self.almacen.listar()})
        self._error(HTTPStatus.NOT_FOUND, "No existe.")

    def _escribir_api(self, accion):
        if not self._host_ok():
            return self._error(HTTPStatus.FORBIDDEN, "Host no permitido.")
        try:
            cuerpo = self._leer_json()
            with LOCK:
                accion(cuerpo)
        except PermissionError as e:
            self._error(HTTPStatus.FORBIDDEN, str(e))
        except FileNotFoundError:
            self._error(HTTPStatus.NOT_FOUND, "El hallazgo ya no existe (¿lo borró otra persona?).")
        except (ValueError, json.JSONDecodeError) as e:
            self._error(HTTPStatus.BAD_REQUEST, str(e))
        except OSError as e:
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"No se pudo escribir en disco: {e.strerror}")

    def do_POST(self):
        ruta = self.path.split("?")[0]
        m = re.fullmatch(r"/api/hallazgos(?:/([0-9a-f]{6}))?", ruta)
        if ruta == "/api/export":
            def exportar(_):
                p = self.almacen.exportar()
                self._responder(HTTPStatus.OK, {"archivo": str(p)})
            return self._escribir_api(exportar)
        if not m:
            return self._error(HTTPStatus.NOT_FOUND, "No existe.")

        def guardar(cuerpo):
            d = limpiar(cuerpo)
            err = validar(d)
            if err:
                raise ValueError(err)
            hid = self.almacen.guardar(m.group(1), d, self.autor)
            self._responder(HTTPStatus.OK, {"id": hid})
        self._escribir_api(guardar)

    def do_DELETE(self):
        m = re.fullmatch(r"/api/hallazgos/([0-9a-f]{6})", self.path.split("?")[0])
        if not m:
            return self._error(HTTPStatus.NOT_FOUND, "No existe.")

        def borrar(_):
            self.almacen.borrar(m.group(1))
            self._responder(HTTPStatus.OK, {"ok": True})
        self._escribir_api(borrar)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--dir", default="docs/alucinaciones", help="carpeta donde se guardan los hallazgos")
    ap.add_argument("--autor", default=None, help="nombre de quien registra (por defecto, git config user.name)")
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()

    Manejador.almacen = Almacen(Path(a.dir))
    Manejador.autor = a.autor or autor_por_defecto()
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Manejador)
    url = f"http://127.0.0.1:{a.port}/"
    print(f"Bitácora de alucinaciones en {url}")
    print(f"  Carpeta: {Path(a.dir).resolve()}")
    print(f"  Registras como: {Manejador.autor}")
    print("  Ctrl+C para cerrar. Recuerda hacer commit de la carpeta para compartir los hallazgos.")
    if not a.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nCerrado.")


if __name__ == "__main__":
    main()
