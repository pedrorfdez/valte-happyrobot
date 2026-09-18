"""Script de validación y diagnóstico para verificar el dataset CSV generado."""

import csv
import sys
import json
from datetime import datetime
from collections import Counter
from typing import List, Dict, Any

# Asegurar compatibilidad con consolas Windows (cp1252 / UTF-8)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from config import LAT_MIN, LAT_MAX, LON_MIN, LON_MAX


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
        "id_llamada", "hora_inicio", "hora_fin", "duracion_segundos",
        "origen", "receptor", "coordenadas", "categoria",
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

    # 4. Validación de Integridad de Datos (Coordenadas, Duraciones, JSONs)
    coord_errors = 0
    duration_errors = 0
    json_parse_errors = 0
    time_distribution = Counter()

    for idx, r in enumerate(rows):
        # Duración
        try:
            t_ini = datetime.fromisoformat(r["hora_inicio"])
            t_fin = datetime.fromisoformat(r["hora_fin"])
            diff = int((t_fin - t_ini).total_seconds())
            dur = int(r["duracion_segundos"])
            if diff != dur:
                duration_errors += 1
            time_distribution[t_ini.hour] += 1
        except Exception:
            duration_errors += 1

        # Coordenadas
        try:
            lat_str, lon_str = r["coordenadas"].split(",")
            lat, lon = float(lat_str), float(lon_str)
            if not (LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX):
                coord_errors += 1
        except Exception:
            coord_errors += 1

        # Transcripción JSON si es diálogo
        if r["tipo_transcripcion"] == "dialogo_operador":
            try:
                parsed = json.loads(r["transcripcion"])
                if not isinstance(parsed, list):
                    json_parse_errors += 1
            except Exception:
                json_parse_errors += 1

    print("\n--- Integridad y Formatos ---")
    print(f"  {'✅' if coord_errors == 0 else '❌'} Coordenadas dentro de zona cero: {total - coord_errors}/{total} válidas")
    print(f"  {'✅' if duration_errors == 0 else '❌'} Cálculo hora_fin - hora_inicio = duracion: {total - duration_errors}/{total} coherentes")
    print(f"  {'✅' if json_parse_errors == 0 else '❌'} Diálogos en JSON parseable: {trans_counts['dialogo_operador'] - json_parse_errors}/{trans_counts['dialogo_operador']} válidos")

    # 5. Visualización del Caos y Picos Horarios
    print("\n--- Curva de Tráfico Temporal (Picos, Llanos y Valles) ---")
    for h in sorted(time_distribution.keys()):
        count = time_distribution[h]
        bar = "█" * int(count * 30 / max(time_distribution.values()))
        print(f"  {h:02d}:00h | {bar} ({count} llamadas)")

    # 6. Muestreo aleatorio de llamadas
    print("\n--- Muestra de Ejemplo (1 Registro) ---")
    sample = rows[0]
    for k, v in sample.items():
        val_preview = v[:100] + "..." if len(v) > 100 else v
        print(f"  {k}: {val_preview}")

    print("\n=======================================================")
    if coord_errors == 0 and duration_errors == 0 and json_parse_errors == 0:
        print("🎉 ¡TODAS LAS VALIDACIONES PASARON EXITOSAMENTE!")
    else:
        print("⚠️ Se detectaron algunas discrepancias a revisar.")
    print("=======================================================\n")


if __name__ == "__main__":
    csv_file = sys.argv[1] if len(sys.argv) > 1 else "llamadas_112_dana.csv"
    verify_dataset(csv_file)
