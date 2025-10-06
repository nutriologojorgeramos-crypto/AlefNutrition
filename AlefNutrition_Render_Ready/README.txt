# AlefNutrition – Nut. Jorge Ramos (Render-ready)

## Ejecutar en local
1) Instala Python 3.10+
2) En la carpeta del proyecto:
   ```bash
   python -m venv .venv
   source .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   python app.py
   ```
3) Abre `http://localhost:5000`
   - Admin: email `admin@alefnutrition.com` – pass `12345`
   - Pacientes: Regístrate en `/register`

### Acceso desde el celular en tu red local
```bash
HOST=0.0.0.0 python app.py
# Luego entra en tu celular a: http://TU-IP-LOCAL:5000
```

## Desplegar en Render
1) Crea cuenta en https://render.com
2) “New +” → “Web Service”
3) Conecta tu repo o sube los archivos (Procfile + requirements.txt ya están listos)
4) Build Command: `pip install -r requirements.txt`
5) Start Command: `gunicorn app:app`
6) Añade variable de entorno (opcional): `SECRET_KEY` con un valor seguro

## Estructura
- `app.py` – servidor Flask
- `templates/` – HTML (Jinja2)
- `static/` – CSS/JS/imágenes
- `uploads/` – fotos de comidas y reportes PDF
- `database.db` – SQLite (se crea/actualiza en el primer arranque)
- `report_templates/` – plantillas de PDF

## Notas
- Contraseñas con hash seguro (Werkzeug)
- Subida de imágenes limitada a: png, jpg, jpeg, gif, webp
- Exportación de reporte PDF por paciente en `/admin` → botón “Descargar PDF`
