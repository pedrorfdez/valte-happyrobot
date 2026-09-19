"""Script de validación y diagnóstico para verificar los datasets CSV generados."""

import csv
import sys
import json
from collections import Counter
from typing import List, Dict, Any

# Asegurar compatibilidad con consolas Windows (cp1252 / UTF-8)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from config import LAT_MIN, LAT_MAX, LON_MIN, LON_MAX
from metadata import ZONAS_CERO


def verify_dataset(csv_path: str = "llamadas_112_dana.csv"):
    print("\n=======================================================")
    print(f"[INFO] Validando dataset sintético: {csv_path}")
    print("=======================================================\n")

    try:
        with open(csv_path, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    except FileNotFoundError:
        print(f"❌ Error: Archivo no encontrado en '{csv_path}'")
        sys.exit(1)

    total = len(rows)
    if total == 0:
        print("❌ Error: El dataset está vacío.")
        sys.exit(1)

    print(f"Total registros analizados: {total}\n")

    # 1. Validación de campos obligatorios
    required_fields = [
        "id_llamada", "inicio", "fin", "duracion_segundos",
        "origen", "receptor", "latitud", "longitud", "categoria",
        "tipo_transcripcion", "transcripcion"
    ]
    missing_fields = set(required_fields) - set(rows[0].keys())
    if missing_fields:
        print(f"❌ Faltan campos en la cabecera: {missing_fields}")
    else:
        print("✅ Todos los campos requeridos están presentes.")

    # 2. Análisis de distribución
    cat_counts = Counter(r["categoria"] for r in rows)
    critica_pct = (cat_counts["critica"] / total) * 100
    urgente_pct = (cat_counts["urgente"] / total) * 100
    ruido_pct = (cat_counts["ruido"] / total) * 100

    print("\n--- Distribución de Negocio (Objetivo: 15% / 25% / 60%) ---")
    print(f"  🔴 Críticas: {cat_counts['critica']} ({critica_pct:.1f}%) [Esperado: ~15%]")
    print(f"  🟠 Urgentes: {cat_counts['urgente']} ({urgente_pct:.1f}%) [Esperado: ~25%]")
    print(f"  ⚪ Ruido:    {cat_counts['ruido']} ({ruido_pct:.1f}%) [Esperado: ~60%]")

    # 3. Tipos de Transcripción
    trans_counts = Counter(r["tipo_transcripcion"] for r in rows)
    print("\n--- Tipos de Transcripción ---")
    for t_type, cnt in trans_counts.items():
        print(f"  • {t_type}: {cnt} ({(cnt/total)*100:.1f}%)")

    # 4. Validación de Integridad de Datos (Coordenadas numéricas, T inicio/fin/duración, JSONs, Semántica)
    coord_errors = 0
    semantic_errors = 0
    duration_errors = 0
    json_parse_errors = 0
    artifact_errors = 0
    transcription_set = set()
    duplicates = 0

    for idx, r in enumerate(rows):
        # Duración y consistencia temporal
        try:
            t_ini = float(r["inicio"])
            t_fin = float(r["fin"])
            dur = float(r["duracion_segundos"])
            if abs((t_fin - t_ini) - dur) > 0.01 or dur <= 0:
                duration_errors += 1
        except Exception:
            duration_errors += 1

        # Coordenadas numéricas en zonas cero
        try:
            lat_val = float(r["latitud"])
            lon_val = float(r["longitud"])
            if not (LAT_MIN <= lat_val <= LAT_MAX and LON_MIN <= lon_val <= LON_MAX):
                coord_errors += 1
            else:
                closest_town, (base_lat, base_lon) = min(
                    ZONAS_CERO.items(),
                    key=lambda x: (lat_val - x[1][0])**2 + (lon_val - x[1][1])**2
                )
                dist = ((lat_val - base_lat)**2 + (lon_val - base_lon)**2)**0.5
                if dist > 0.008:
                    coord_errors += 1
                elif closest_town.lower() not in r["transcripcion"].lower():
                    semantic_errors += 1
        except Exception:
            coord_errors += 1

        # Transcripción duplicada
        txt = r["transcripcion"]
        if txt in transcription_set:
            duplicates += 1
        transcription_set.add(txt)

        # Transcripción JSON si es diálogo
        if r["tipo_transcripcion"] == "dialogo_operador":
            try:
                parsed = json.loads(txt)
                if not isinstance(parsed, list):
                    json_parse_errors += 1
                else:
                    for turn in parsed:
                        t_text = turn.get("texto", "").strip()
                        if t_text in ["...", "..", ".", "[Silencio]", "[silencio]", ""] or set(t_text).issubset({".", " ", "…"}):
                            artifact_errors += 1
            except Exception:
                json_parse_errors += 1
        else:
            if txt.strip() in ["...", "..", ".", "[Silencio]", "[silencio]", ""] or set(txt.strip()).issubset({".", " ", "…"}):
                artifact_errors += 1

    print("\n--- Integridad y Formatos ---")
    print(f"  {'✅' if coord_errors == 0 else '❌'} Coordenadas válidas en zonas cero: {total - coord_errors}/{total}")
    print(f"  {'✅' if semantic_errors == 0 else '❌'} Coherencia semántica (municipio presente en texto): {total - semantic_errors}/{total}")
    print(f"  {'✅' if duration_errors == 0 else '❌'} Consistencia temporal fin - inicio = duracion: {total - duration_errors}/{total}")
    print(f"  {'✅' if json_parse_errors == 0 else '❌'} Diálogos parseables en JSON: {trans_counts['dialogo_operador'] - json_parse_errors}/{trans_counts['dialogo_operador']}")
    print(f"  {'✅' if artifact_errors == 0 else '❌'} Ausencia de artefactos mudos ('...', '[Silencio]'): {total - artifact_errors}/{total}")
    print(f"  {'✅' if duplicates == 0 else '❌'} Transcripciones únicas (sin duplicados): {total - duplicates}/{total}")

    # 5. Rango de T y Duraciones
    inicios = []
    duraciones = []
    for r in rows:
        try:
            inicios.append(float(r["inicio"]))
            duraciones.append(float(r["duracion_segundos"]))
        except Exception:
            pass
    if inicios and duraciones:
        print("\n--- Rango Temporal T ---")
        print(f"  • Rango T inicio: [{min(inicios):.2f} -> {max(inicios):.2f}]")
        print(f"  • Duración llamadas: Mín {min(duraciones):.0f}s | Media {sum(duraciones)/len(duraciones):.1f}s | Máx {max(duraciones):.0f}s")

    # 6. Muestreo de registros de ejemplo
    print("\n--- Muestra de Ejemplo (Primer Registro) ---")
    sample = rows[0]
    for k, v in sample.items():
        val_preview = v[:120] + "..." if len(str(v)) > 120 else str(v)
        print(f"  {k}: {val_preview}")

    print("\n=======================================================")
    if (coord_errors == 0 and semantic_errors == 0 and duration_errors == 0 
        and json_parse_errors == 0 and artifact_errors == 0 and duplicates == 0):
        print("🎉 ¡TODAS LAS VALIDACIONES PASARON EXITOSAMENTE!")
    else:
        print("⚠️ Se detectaron algunas discrepancias a revisar.")
    print("=======================================================\n")


if __name__ == "__main__":
    csv_file = sys.argv[1] if len(sys.argv) > 1 else "llamadas_112_dana.csv"
    verify_dataset(csv_file)
