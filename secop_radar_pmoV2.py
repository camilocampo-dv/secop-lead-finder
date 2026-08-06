# -*- coding: utf-8 -*-
"""
RADAR SECOP II - Detector de leads para consultoria PMO  (v2)
=============================================================
Consulta el dataset "SECOP II - Contratos Electronicos" (jbjy-vk9h) en
datos.gov.co via API Socrata (SODA) y detecta EMPRESAS PRIVADAS MEDIANAS
que acaban de ganar varios contratos publicos en poco tiempo: candidatas
a saturarse operativamente y a necesitar gobernanza de entrega.

CAMBIOS FRENTE A v1
-------------------
1. Score corregido. En v1 el maximo estructural era 29 (15+10+4) y todos
   los resultados del top saturaban los tres topes, asi que el ranking no
   discriminaba. v2 usa un rango de ~0-72 con componentes independientes.
2. Valor con "punto dulce" en vez de premio monotono. v1 daba mas puntos
   mientras mas grande el proveedor, empujando hacia organizaciones que
   YA tienen PMO. v2 penaliza a los gigantes.
3. Exclusion de entidades publicas. El filtro `like '%NIT%'` de v1 no las
   excluia (las entidades estatales tambien tienen NIT); solo descartaba
   personas naturales. v2 filtra por patrones de razon social.
4. Diversidad de clientes y recencia como senales adicionales.
5. Geografia configurable, por defecto Bogota y Cundinamarca.

USO:
    pip3 install requests pandas
    python3 secop_radar_pmo.py

Salida: secop_leads_YYYY-MM-DD.csv con proveedores rankeados.
"""

import os
import re
import requests
import pandas as pd
from datetime import datetime, timedelta

# ----------------------- CONFIGURACION -----------------------
APP_TOKEN = os.getenv("SOCRATA_APP_TOKEN", "")  # opcional; sube el limite de peticiones
DIAS_ATRAS = 60                   # ventana de contratos firmados
VALOR_MINIMO_COP = 500_000_000    # contrato individual minimo
VALOR_MAXIMO_COP = 20_000_000_000 # excluye megacontratos
DEPARTAMENTOS = ["Distrito Capital de Bogotá", "Cundinamarca"]  # [] = todo el pais
EXCLUIR_ENTIDADES_PUBLICAS = True
MIN_CONTRATOS = 2                 # el lead util gano MAS DE UNO
MAX_FILAS = 20000
TOP_N_CONSOLA = 15

KEYWORDS_OBJETO = [
    "software", "tecnolog", "sistema de informaci", "implementaci",
    "interventor", "consultor", "ingenier", "infraestructura",
    "desarrollo", "plataforma", "migraci", "integraci",
]

# Patrones de razon social tipicos de entidades publicas y de organizaciones
# que no son clientes viables para consultoria de entrega.
PATRONES_PUBLICOS = [
    r"\bUNIVERSIDAD\b", r"\bINSTITUCI[OÓ]N UNIVERSITARIA\b", r"\bPOLIT[EÉ]CNICO\b",
    r"\bMUNICIPIO\b", r"\bALCALD[IÍ]A\b", r"\bGOBERNACI[OÓ]N\b", r"\bDEPARTAMENTO DE\b",
    r"\bMINISTERIO\b", r"\bAGENCIA\b", r"\bINSTITUTO\b", r"\bSUPERINTENDENCIA\b",
    r"\bEMPRESA (DE|SOCIAL|INDUSTRIAL)\b", r"\bE\.?S\.?E\.?\b", r"\bE\.?I\.?C\.?E\.?\b",
    r"\bHOSPITAL\b", r"\bCAJA DE COMPENSACI[OÓ]N\b", r"\bCORPORACI[OÓ]N\b",
    r"\bFONDO\b", r"\bC[AÁ]MARA DE COMERCIO\b", r"\bESCUELA\b", r"\bCOLEGIO\b",
    r"\bSENA\b", r"\bICBF\b", r"\bPOLIC[IÍ]A\b", r"\bEJ[EÉ]RCITO\b", r"\bFUERZA\b",
    r"\bTERRITORIAL\b", r"\bMETROPARQUES\b", r"\bASOCIACI[OÓ]N\b", r"\bFUNDACI[OÓ]N\b",
    r"\bPREVISORA\b", r"\bPLAZA MAYOR\b", r"\bSEGURIDAD URBANA\b", r"\bTERMINAL\b",
    r"\bAEROPUERTO\b", r"\bACUEDUCTO\b", r"\bLOTER[IÍ]A\b", r"\bCONCEJO\b",
    r"\bPERSONER[IÍ]A\b", r"\bCONTRALOR[IÍ]A\b", r"\bREGISTRADUR[IÍ]A\b",
    # Anadidos tras la corrida de agosto: casos que se colaron en el top 15
    r"\bSECRETAR[IÍ]A\b", r"\bDISTRITAL\b", r"\bE\.?\s?S\.?\s?P\.?(\b|$)",
    r"\bSERVICIOS POSTALES NACIONALES\b", r"\bCOLOMBO AMERICANO\b",
    r"\bCAFAM\b", r"\bCOMFA", r"\bCOMPENSAR\b", r"\bCOLSUBSIDIO\b",
]

# NOTA DE LIMITACION: el filtrado por razon social es una aproximacion. La
# solucion definitiva es cruzar el NIT del proveedor contra un registro de
# entidades publicas. Sociedades de economia mixta y descentralizadas con
# nombre comercial pueden seguir pasando el filtro.

DATASET_URL = "https://www.datos.gov.co/resource/jbjy-vk9h.json"
CAMPOS = ("proveedor_adjudicado, documento_proveedor, nombre_entidad, "
          "departamento, ciudad, valor_del_contrato, fecha_de_firma, "
          "tipo_de_contrato, modalidad_de_contratacion, "
          "descripcion_del_proceso, urlproceso")
# --------------------------------------------------------------


def construir_where():
    fecha_corte = (datetime.now() - timedelta(days=DIAS_ATRAS)).strftime("%Y-%m-%dT00:00:00")
    cond = [
        f"fecha_de_firma >= '{fecha_corte}'",
        f"valor_del_contrato >= {VALOR_MINIMO_COP}",
        f"valor_del_contrato <= {VALOR_MAXIMO_COP}",
        "upper(tipodocproveedor) like '%NIT%'",   # descarta personas naturales
    ]
    if DEPARTAMENTOS:
        deps = ", ".join("'{}'".format(d) for d in DEPARTAMENTOS)
        cond.append(f"departamento in ({deps})")
    return " AND ".join(cond)


def consultar_secop():
    params = {
        "$where": construir_where(),
        "$select": CAMPOS,
        "$order": "fecha_de_firma DESC",
        "$limit": MAX_FILAS,
    }
    headers = {"X-App-Token": APP_TOKEN} if APP_TOKEN else {}
    ambito = ", ".join(DEPARTAMENTOS) if DEPARTAMENTOS else "todo el pais"
    print(f"Consultando SECOP II | ultimos {DIAS_ATRAS} dias | {ambito}")
    r = requests.get(DATASET_URL, params=params, headers=headers, timeout=120)
    if r.status_code == 400:
        print("ERROR 400 - probable cambio en nombres de campos del dataset.")
        print("Detalle de la API:", r.text[:500])
        print("Campos vigentes: https://dev.socrata.com/foundry/www.datos.gov.co/jbjy-vk9h")
        raise SystemExit(1)
    r.raise_for_status()
    return pd.DataFrame(r.json())


def es_entidad_publica(nombre):
    """True si la razon social coincide con patrones de entidad publica."""
    if not isinstance(nombre, str):
        return False
    n = nombre.upper()
    return any(re.search(p, n) for p in PATRONES_PUBLICOS)


def puntos_valor(valor_cop):
    """
    Punto dulce en vez de premio monotono.

    La tesis del radar es encontrar empresas MEDIANAS que acaban de ganar
    volumen. Premiar el valor total sin techo empuja hacia los gigantes,
    que ya tienen PMO. Esta curva sube hasta ~3.000M, se mantiene hasta
    ~10.000M y luego decae.
    """
    v = valor_cop / 1e9  # a miles de millones
    if v < 0.5:
        return 0.0
    if v < 3:
        return round(v / 3 * 20, 1)      # rampa de subida
    if v <= 10:
        return 20.0                       # meseta: el punto dulce
    return round(max(0.0, 20 - (v - 10) * 1.3), 1)   # decaimiento: gigantes


def puntuar_leads(df):
    if df.empty:
        print("Sin resultados. Amplia la ventana de dias o baja el valor minimo.")
        raise SystemExit(0)

    df["valor_del_contrato"] = pd.to_numeric(df["valor_del_contrato"], errors="coerce")
    df["descripcion_del_proceso"] = df.get("descripcion_del_proceso", pd.Series(dtype=str)).fillna("")
    df["fecha_de_firma"] = pd.to_datetime(df["fecha_de_firma"], errors="coerce")

    if EXCLUIR_ENTIDADES_PUBLICAS:
        antes = df["proveedor_adjudicado"].nunique()
        df = df[~df["proveedor_adjudicado"].apply(es_entidad_publica)].copy()
        despues = df["proveedor_adjudicado"].nunique()
        print(f"Proveedores publicos excluidos: {antes - despues} de {antes}")
        if df.empty:
            print("Todo el resultado era entidad publica. Amplia la ventana o la geografia.")
            raise SystemExit(0)

    patron = "|".join(KEYWORDS_OBJETO)
    df["match_keyword"] = df["descripcion_del_proceso"].str.lower().str.contains(patron, na=False)

    resumen = (df.groupby(["proveedor_adjudicado", "documento_proveedor"], dropna=False)
                 .agg(contratos=("valor_del_contrato", "size"),
                      entidades_distintas=("nombre_entidad", "nunique"),
                      valor_total_cop=("valor_del_contrato", "sum"),
                      valor_max_cop=("valor_del_contrato", "max"),
                      entidades=("nombre_entidad", lambda s: "; ".join(sorted(set(s))[:3])),
                      ciudades=("ciudad", lambda s: "; ".join(sorted(set(s.dropna()))[:3])),
                      con_keyword=("match_keyword", "any"),
                      ultima_firma=("fecha_de_firma", "max"),
                      ejemplo_objeto=("descripcion_del_proceso", "first"),
                      url_ejemplo=("urlproceso", "first"))
                 .reset_index())

    resumen = resumen[resumen["contratos"] >= MIN_CONTRATOS].copy()
    if resumen.empty:
        print(f"Ningun proveedor con {MIN_CONTRATOS}+ contratos. Baja MIN_CONTRATOS o amplia la ventana.")
        raise SystemExit(0)

    hoy = pd.Timestamp.now().normalize()
    resumen["dias_desde_ultima"] = (hoy - resumen["ultima_firma"].dt.normalize()).dt.days

    # ---- Componentes del score (independientes, sin saturacion comun) ----
    # Volumen de adjudicaciones: la senal mas fuerte de choque operativo.
    resumen["p_volumen"] = resumen["contratos"].clip(upper=12) * 2          # 0-24
    # Tamano: curva de punto dulce, penaliza gigantes.
    resumen["p_valor"] = resumen["valor_total_cop"].apply(puntos_valor)     # 0-20
    # Diversidad: varios clientes distintos = mas complejidad de coordinacion.
    resumen["p_diversidad"] = resumen["entidades_distintas"].clip(upper=5) * 2  # 0-10
    # Relevancia del objeto para tu nicho.
    resumen["p_objeto"] = resumen["con_keyword"].astype(int) * 5           # 0-5
    # Recencia: entre mas fresco, mas ventana tienes para llegar antes.
    resumen["p_recencia"] = resumen["dias_desde_ultima"].apply(
        lambda d: 5 if d <= 15 else (3 if d <= 30 else 1))                 # 1-5

    resumen["score"] = (resumen["p_volumen"] + resumen["p_valor"]
                        + resumen["p_diversidad"] + resumen["p_objeto"]
                        + resumen["p_recencia"]).round(1)

    resumen = resumen.sort_values(["score", "valor_total_cop"], ascending=False)
    resumen["valor_total_mm"] = (resumen["valor_total_cop"] / 1e6).round(0)
    return resumen


def main():
    df = consultar_secop()
    print(f"Contratos descargados: {len(df)}")
    leads = puntuar_leads(df)

    salida = f"secop_leads_{datetime.now():%Y-%m-%d}.csv"
    leads.to_csv(salida, index=False, encoding="utf-8-sig")

    print(f"\nTop {TOP_N_CONSOLA} leads:\n")
    vista = leads.head(TOP_N_CONSOLA).copy()
    vista["proveedor"] = vista["proveedor_adjudicado"].str.slice(0, 42)
    vista["valor_MM"] = vista["valor_total_mm"].map("{:,.0f}".format)
    cols = ["proveedor", "contratos", "entidades_distintas", "valor_MM", "score"]
    print(vista[cols].to_string(index=False))

    print(f"\nRango de score en el resultado: "
          f"{leads['score'].min():.1f} - {leads['score'].max():.1f} "
          f"(si estos dos numeros son iguales, el score volvio a saturarse)")
    print(f"Archivo completo: {salida}")
    print("Siguiente paso: verificar tamano en LinkedIn (punto dulce 20-200 "
          "empleados) e identificar CEO o Gerente General.")


if __name__ == "__main__":
    main()
