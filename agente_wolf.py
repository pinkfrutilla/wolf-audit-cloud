import asyncio
import time
import requests
import schedule
from pysnmp.hlapi.v3arch.asyncio import (
    SnmpEngine, CommunityData, UdpTransportTarget,
    ContextData, ObjectType, ObjectIdentity, get_cmd
)

# --- 1. URL DE TU API EN RENDER ---
API_WOLF_URL = "https://wolf-audit-cloud-3.onrender.com/api/guardar"

# --- 2. CONFIGURACIÓN DE TU MAQUETA (Ajustar IPs en el laboratorio) ---
IP_MC_LOCAL = "192.168.10.21"    # Media Converter 1 (conectado al Switch 1)
IP_MC_REMOTO = "192.168.10.22"   # Media Converter 2 (al otro extremo de la fibra)
COMUNIDAD_SNMP = "public"        # Comunidad SNMP de lectura

# OID estándar multimarca: ifOperStatus (1 = UP, 2 = DOWN)
# Cambia el último número (.2) por el número de puerto de fibra del Media Converter
OID_ESTADO_PUERTO_FIBRA = "1.3.6.1.2.1.2.2.1.8.2"

# OID opcional de potencia Rx óptica (DOM) - reemplazar según el modelo exacto TP-Link
OID_POTENCIA_RX = None  # Ej: "1.3.6.1.4.1.11863.6.45.1.1.1.1.5.2"

SENSIBILIDAD_SRX = -22.0  # dBm


async def _consultar_snmp_async(ip, oid):
    snmp_engine = SnmpEngine()
    try:
        transport = await UdpTransportTarget.create((ip, 161), timeout=2.0, retries=1)
        error_indication, error_status, error_index, var_binds = await get_cmd(
            snmp_engine,
            CommunityData(COMUNIDAD_SNMP, mpModel=1),
            transport,
            ContextData(),
            ObjectType(ObjectIdentity(oid))
        )
        if error_indication or error_status:
            return None
        for _, val in var_binds:
            return str(val)
        return None
    except Exception:
        return None
    finally:
        if hasattr(snmp_engine, "close_dispatcher"):
            snmp_engine.close_dispatcher()


def consultar_snmp(ip, oid):
    """Consulta un OID por SNMPv2c y devuelve el valor, o None si no responde."""
    return asyncio.run(_consultar_snmp_async(ip, oid))


def auditar_enlace_real():
    print("\n--- Consultando maqueta física por SNMP ---")

    # 1. Revisar puerto de fibra en Media Converter 1 (Local)
    estado_mc1 = consultar_snmp(IP_MC_LOCAL, OID_ESTADO_PUERTO_FIBRA)

    # 2. Revisar conectividad hacia Media Converter 2 (al otro lado de las fibras)
    estado_mc2 = consultar_snmp(IP_MC_REMOTO, OID_ESTADO_PUERTO_FIBRA)

    # 3. Evaluar estado real de la fibra
    if estado_mc1 is None:
        estado_texto = "ERROR GESTION: Sin respuesta del Media Converter Local"
        margen_db = 0.0
        evento_km = 3.0
    elif estado_mc1 != "1" or estado_mc2 is None or estado_mc2 != "1":
        estado_texto = "FALLA CRÍTICA: Corte de Fibra / Pérdida de Señal (LOS)"
        margen_db = 0.0
        evento_km = 3.0
    else:
        if OID_POTENCIA_RX:
            rx_raw = consultar_snmp(IP_MC_LOCAL, OID_POTENCIA_RX)
            prx = float(rx_raw) if rx_raw else -17.5
        else:
            prx = -17.5

        margen_db = round(prx - SENSIBILIDAD_SRX, 2)

        if margen_db < 1.5:
            estado_texto = "FALLA CRÍTICA: Atenuación Excesiva en Fibra"
            evento_km = 1.80
        elif margen_db < 3.0:
            estado_texto = "Caso T2: Pérdida Preventiva (Hardware)"
            evento_km = 0.45
        else:
            # Exactamente este texto para que pg_cron lo limpie a los 30 días
            estado_texto = "Caso T1: Enlace Sano"
            evento_km = 0.10

    payload = {
        "enlace_id": "MAQUETA-TPLINK-SEDE",
        "evento_km": evento_km,
        "margen_db": margen_db,
        "estado": estado_texto
    }

    print(f"Resultado: {payload}")

    # 4. Empujar (Push) hacia tu servidor en Render
    try:
        resp = requests.post(API_WOLF_URL, json=payload, timeout=60)
        print(f"Respuesta Render ({resp.status_code}): {resp.json()}")
    except Exception as e:
        print(f"Error enviando a la nube: {e}")


# Ejecutar una lectura inmediata al encender el script y luego cada 1 minuto
auditar_enlace_real()
schedule.every(1).minutes.do(auditar_enlace_real)

print("Agente WOLF-Audit activo. Monitoreando cada 1 minuto (Ctrl+C para detener)...")
while True:
    schedule.run_pending()
    time.sleep(1)