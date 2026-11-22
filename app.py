"""OndeTem 3.0 — Ponto de entrada do servidor FastAPI/Uvicorn.

Execute `python app.py` (ou `uvicorn ondetem.web:app --reload`) e abra http://127.0.0.1:8001.
"""

from __future__ import annotations

import os

import uvicorn

from ondetem.config import DATABASE_URL, HOST, PORT, READ_ONLY_DEMO


def main() -> None:
    db_mode = "PostgreSQL (nuvem)" if DATABASE_URL else "SQLite (local)"
    mode = "SOMENTE LEITURA" if READ_ONLY_DEMO else "COMPLETO"
    reload_enabled = os.environ.get("ONDETEM_RELOAD", "1") == "1" and not DATABASE_URL
    print(f"OndeTem 3.0 [{mode} | {db_mode}] rodando em http://{HOST}:{PORT}")
    uvicorn.run("ondetem.web:app", host=HOST, port=PORT, reload=reload_enabled)


if __name__ == "__main__":
    main()
