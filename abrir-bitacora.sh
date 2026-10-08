#!/usr/bin/env bash
# Doble clic (o ./abrir-bitacora.sh) para abrir la bitácora de alucinaciones.
cd "$(dirname "$0")" || exit 1
if command -v python3 >/dev/null 2>&1; then
  python3 tools/bitacora/server.py
elif command -v python >/dev/null 2>&1; then
  python tools/bitacora/server.py
else
  echo "No se encontró Python. Instálalo desde https://www.python.org/downloads/"
  read -r -p "Pulsa Enter para cerrar"
fi
