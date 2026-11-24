from flask import Flask, render_template, request, jsonify
from supabase import create_client, Client
import os

app = Flask(__name__)

# La nube inyecta estas credenciales desde Render
URL = os.environ.get("SUPABASE_URL", "")
KEY = os.environ.get("SUPABASE_KEY", "")

# Conexión a Supabase
supabase: Client = None
if URL and KEY:
    supabase = create_client(URL, KEY)

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/api/guardar', methods=['POST'])
def guardar_auditoria():
    if not supabase:
        return jsonify({"error": "Base de datos no conectada"}), 500
    
    datos = request.json
    try:
        respuesta = supabase.table('auditorias').insert(datos).execute()
        return jsonify({"mensaje": "¡Auditoría guardada en la Nube!", "data": respuesta.data})
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route('/api/ultima-lectura', methods=['GET'])
def ultima_lectura():
    if not supabase:
        return jsonify({"error": "Base de datos no conectada"}), 500
    
    try:
        # Trae el registro más reciente guardado en Supabase
        respuesta = (
            supabase.table('auditorias')
            .select('*')
            .order('id', desc=True)
            .limit(1)
            .execute()
        )
        if respuesta.data:
            return jsonify(respuesta.data[0])
        return jsonify({"mensaje": "Aún no hay lecturas"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 400

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)