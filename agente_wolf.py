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

# --- 2. IPs DE LOS SWITCHES CISCO 2960 ---
IP_SW_LOCAL = "192.168.10.11"    # Cisco SW1 (conectado a tu laptop y Comdiel 1)
IP_SW_REMOTO = "192.168.10.12"   # Cisco SW2 (al otro lado de la fibra y Comdiel 2)
COMUNIDAD_SNMP = "public"

# OID universal de vida del equipo (funciona en cualquier marca)
OID_SYS_UPTIME = "1.3.6.1.2.1.1.3.0"

# OID de errores físicos de entrada/CRC en Fa0/2 del Cisco 2960 (ifIndex 10002)
OID_CRC_FA02 = "1.3.6.1.2.1.2.2.1.14.10002"

errores_previos = None


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
    return asyncio.run(_consultar_snmp_async(ip, oid))


def auditar_enlace_real():
    global errores_previos
    print("\n--- Consultando maqueta Cisco + Fibra Comdiel por SNMP ---")

    sw1_ok = consultar_snmp(IP_SW_LOCAL, OID_SYS_UPTIME)
    sw2_ok = consultar_snmp(IP_SW_REMOTO, OID_SYS_UPTIME)

    # Lectura opcional de errores CRC en puerto Fa0/2 del SW1
    crc_nuevos = 0
    if sw1_ok is not None:
        crc_raw = consultar_snmp(IP_SW_LOCAL, OID_CRC_FA02)
        try:
            crc_actual = int(crc_raw)
            if errores_previos is not None and crc_actual > errores_previos:
                crc_nuevos = crc_actual - errores_previos
            errores_previos = crc_actual
        except (TypeError, ValueError):
            pass

    # Diagnóstico real de la capa física
    if sw1_ok is None:
        estado_texto = "ERROR GESTION: Sin respuesta de Cisco SW1 Local"
        margen_db = 0.0
        evento_km = 3.0
    elif sw2_ok is None:
        # SW1 responde pero SW2 cayó -> corte real en el enlace de fibra
        estado_texto = "FALLA CRÍTICA: Corte de Fibra / Pérdida de Señal (LOS)"
        margen_db = 0.0
        evento_km = 3.0
    elif crc_nuevos > 0:
        # La fibra no se cortó del todo, pero está generando tramas corruptas (CRC)
        estado_texto = f"ALERTA PREVENTIVA: Degradación Óptica ({crc_nuevos} errores CRC)"
        margen_db = 1.8
        evento_km = 0.45
    else:
        # Exactamente este texto para que pg_cron lo limpie a los 30 días
        estado_texto = "Caso T1: Enlace Sano"
        margen_db = 4.5
        evento_km = 0.10

    payload = {
        "enlace_id": "MAQUETA-CISCO-COMDIEL",
        "evento_km": evento_km,
        "margen_db": margen_db,
        "estado": estado_texto
    }

    print(f"SW1={bool(sw1_ok)} | SW2={bool(sw2_ok)} | CRC nuevos={crc_nuevos}")
    print(f"Enviando a nube: {payload}")

    try:
        resp = requests.post(API_WOLF_URL, json=payload, timeout=60)
        print(f"Respuesta Render ({resp.status_code}): {resp.json()}")
    except Exception as e:
        print(f"Error enviando a la nube: {e}")


auditar_enlace_real()
# Para probar rápido ahora puedes cambiar '1' por '10' segundos (.seconds)
# y dejarlo en .minutes para la evaluación si el profe pide cada 1 minuto
schedule.every(1).minutes.do(auditar_enlace_real)

print("Agente WOLF-Audit activo. Monitoreando maqueta física (Ctrl+C para detener)...")
while True:
    schedule.run_pending()
    time.sleep(1)
