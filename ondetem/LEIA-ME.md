# OndeTem 3.0 — FastAPI + PostgreSQL (Manaus)

Plataforma web e API REST mobile-first para conectar moradores de Manaus a profissionais autônomos de manutenção e reparos.

## 1. Rodar localmente no VS Code (SQLite automático)

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
uvicorn ondetem.web:app --reload --port 8001
```

Acesse:
- **Aplicação:** http://127.0.0.1:8001
- **Documentação interativa da API (Swagger):** http://127.0.0.1:8001/docs
- **Healthcheck:** http://127.0.0.1:8001/api/health

## 2. Conectar ao banco PostgreSQL na nuvem (Neon ou Supabase)

1. Crie um banco PostgreSQL gratuito no **Neon** (neon.tech) ou **Supabase** (supabase.com).
2. Copie a *Connection String* (`postgresql://...`).
3. Abra seu arquivo `.env` e cole:
   ```env
   DATABASE_URL=postgresql://usuario:senha@host/banco?sslmode=require
   ```
4. Reinicie o servidor (`uvicorn ondetem.web:app --reload --port 8001`). As tabelas e dados iniciais serão criados automaticamente no PostgreSQL!

## 3. Subir no ar com HTTPS grátis (Render.com)

1. Suba esta pasta para um repositório no **GitHub**.
2. No **Render** (render.com), clique em **New → Blueprint** e conecte seu repositório.
3. O arquivo `render.yaml` cria automaticamente o **Servidor Web FastAPI** + o **Banco PostgreSQL** já conectados com HTTPS.

## Testes automatizados

```powershell
python -m unittest discover -s tests -v
```
