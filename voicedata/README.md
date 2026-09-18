# voicemock: Generador Sintético de Llamadas 112 (DANA Valencia)

Generador asíncrono y de alto rendimiento de llamadas de emergencias al 112 durante el colapso de la DANA de Valencia. Diseñado para estresar y validar sistemas agénticos de triaje y despacho de emergencias en tiempo real.

## 🚀 Características

- **Distribución de Caos Realista (Señal/Ruido):**
  - **15% Críticas (Señal alta):** Personas atrapadas en tejados/coches, riesgo vital inminente, agua superando plantas bajas, muros colapsados.
  - **25% Urgentes (Señal media):** Daños materiales, garajes inundados, animales atrapados, evacuaciones preventivas.
  - **60% Ruido (Saturación/Basura):** Cortes a los 2-3 segundos, silencios/estática, quejas por cortes de luz, dudas de seguros, llamadas fuera de lugar.
- **Modelado Temporal con Picos y Valles:**
  - Simula el 20 de diciembre a lo largo del día.
  - Distribución de intensidad horaria: calma matinal, repunte vespertino y colapso masivo en las horas pico de inundación (16:00 - 21:00).
- **Esquema de Datos en CSV:**
  - `id_llamada`: Identificador único UUIDv4.
  - `hora_inicio`: Timestamp ISO 8601 de inicio de la llamada.
  - `hora_fin`: Timestamp ISO 8601 de finalización.
  - `duracion_segundos`: Duración calculada (`hora_fin - hora_inicio`).
  - `origen`: Teléfono simulado (+34 móvil/fijo Valencia).
  - `receptor`: Identificador del receptor (`operador_112_val_#...` o `centralita_automatica_saturada`).
  - `coordenadas`: Latitud y longitud numéricas dentro del polígono más afectado (Paiporta, Chiva, Utiel, etc.).
  - `categoria`: `critica`, `urgente`, `ruido`.
  - `tipo_transcripcion`: `monologo_centralita` o `dialogo_operador`.
  - `transcripcion`:
    - **String directo:** Cuando la llamada cayó en saturación y el ciudadano habla ante el contestador.
    - **JSON serializado:** Diálogo estructurado entre el operador y el ciudadano cuando la llamada fue atendida.
- **Resiliencia & Rate Limiting:**
  - Control de concurrencia con `asyncio.Semaphore`.
  - Reintentos con *Exponential Backoff*.
  - Streaming directo fila a fila en el CSV para no agotar la RAM en ejecuciones masivas.
  - Modo **Mock integrado** para pruebas instantáneas y desarrollo a coste cero (sin necesidad de API key).

---

## 📦 Instalación

Requiere Python 3.10+:

```bash
pip install -r requirements.txt
```

---

## ⚙️ Configuración (Opcional para OpenAI)

Copia el archivo de ejemplo a `.env`:

```bash
cp .env.example .env
```

Y añade tu clave de OpenAI:
```env
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
MAX_CONCURRENCY=10
```

> **Nota:** Si no se define `OPENAI_API_KEY`, el generador se ejecuta automáticamente en modo **Mock** con un banco sintético offline ultra-realista.

---

## 💻 Uso

### 1. Generación de lote piloto (100 llamadas por defecto)
```bash
python main.py
```

### 2. Generación personalizada (ej. 500 llamadas a un archivo específico)
```bash
python main.py --num-calls 500 --output dataset_dana_500.csv
```

### 3. Forzar modo Mock (incluso teniendo API key configurada)
```bash
python main.py --num-calls 100 --mock
```

### 4. Opciones disponibles en el CLI
```bash
python main.py --help

Opciones:
  -n, --num-calls NUM    Número de llamadas a generar (por defecto: 100)
  -o, --output RUTA      Archivo CSV de destino (por defecto: llamadas_112_dana.csv)
  --mock                 Forzar modo mock sin consumir API de OpenAI
  -c, --concurrency N    Concurrencia máxima de peticiones LLM (por defecto: 10)
  -m, --model MODEL      Modelo LLM de OpenAI a utilizar (por defecto: gpt-4o-mini)
```

---

## 🔍 Verificación del Dataset

Para auditar y comprobar que el CSV cumple rigurosamente con todas las reglas de negocio, duraciones, coordenadas y la curva de picos/valles:

```bash
python verify.py llamadas_112_dana.csv
```
