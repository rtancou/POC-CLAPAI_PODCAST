import os
import re
import argparse
import json
from typing import TypedDict
from langgraph.graph import StateGraph, END
from openai import OpenAI

# Optional: carga variables de entorno desde un archivo .env si existe
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# ==========================================
# 1. Definición del Estado
# ==========================================
class PodcastState(TypedDict):
    guion_crudo: str
    guion_limpio: str
    mp3_filepath: str
    estado_revision: str
    meta: dict


def seleccionar_voz_por_genero(gender: str) -> str:
    """Mapeo simple y estable de genero a voz base soportada por tts-1."""
    g = (gender or "").strip().lower()
    if g.startswith("f"):
        return "nova"
    return "onyx"

# ==========================================
# 2. Definición de Nodos (Agentes)
# ==========================================

def agente_1_ingesta(state: PodcastState) -> dict:
    """Agente 1: Recibe el guion del usuario y lo prepara para el flujo."""
    print("Agente 1: Recibiendo el guion original...")
    # En un caso real, este agente podría leer un archivo .txt o un Word.
    # Aquí simplemente pasamos el texto crudo al siguiente agente.
    return {"guion_crudo": state.get("guion_crudo", "")}

def agente_2_director(state: PodcastState) -> dict:
    """Agente 2: Limpia metadatos, acotaciones y etiquetas de locutor."""
    print("Agente 2: Director en acción... Limpiando el guion para la grabación.")
    texto = state.get("guion_crudo", "")

    # 0. Si el guion llega como tabla Markdown, extraer solo la columna "Voz en off"
    # para evitar narrar encabezados o columnas de apoyo visual.
    if "|" in texto and "voz en off" in texto.lower():
        lineas = [ln.strip() for ln in texto.splitlines() if ln.strip()]
        header_idx = None
        voz_col_idx = None
        for i, ln in enumerate(lineas):
            if ln.startswith("|") and ln.endswith("|") and "voz en off" in ln.lower():
                header_idx = i
                cols = [c.strip().lower() for c in ln.strip("|").split("|")]
                for j, col in enumerate(cols):
                    if "voz en off" in col:
                        voz_col_idx = j
                        break
                break

        if header_idx is not None and voz_col_idx is not None:
            narracion = []
            for ln in lineas[header_idx + 1:]:
                if not (ln.startswith("|") and ln.endswith("|")):
                    continue
                # saltar separadores tipo |----|
                if set(ln.replace("|", "").replace("-", "").replace(":", "").strip()) == set():
                    continue
                cols = [c.strip() for c in ln.strip("|").split("|")]
                if voz_col_idx < len(cols) and cols[voz_col_idx]:
                    narracion.append(cols[voz_col_idx])

            if narracion:
                texto = "\n\n".join(narracion)
    
    # 1. Extraer solo la parte del guion (ignoramos Título, Objetivo, Duración)
    if "Guion completo:" in texto:
        texto = texto.split("Guion completo:")[1]
        
    # 2. Eliminar las etiquetas de sección (ej. "(SECCIÓN 1: Entender dónde...)")
    # Usamos una expresión regular para borrar todo lo que esté entre paréntesis
    # y empiece con "SECCIÓN"
    texto = re.sub(r'\(SECCIÓN.*?\)', '', texto, flags=re.IGNORECASE)
    
    # 3. Eliminar la palabra "LOCUTOR:"
    texto = texto.replace("LOCUTOR:", "")
    
    # 4. Limpiar espacios en blanco y saltos de línea sobrantes
    texto = re.sub(r'\n\s*\n', '\n\n', texto).strip()

    # 5. Limpieza adicional de Markdown para evitar narrar formato/etiquetas.
    # - elimina encabezados, listas de transiciones y separadores de tabla
    # - conserva texto natural narrable
    lineas_limpias = []
    skip_transiciones = False
    for ln in texto.splitlines():
        raw = ln.strip()
        low = raw.lower()

        if not raw:
            lineas_limpias.append("")
            continue

        if low.startswith("transiciones sugeridas"):
            skip_transiciones = True
            continue

        if skip_transiciones and (raw.startswith("-") or raw.startswith("*")):
            continue
        if skip_transiciones and not (raw.startswith("-") or raw.startswith("*")):
            skip_transiciones = False

        # Quitar encabezados markdown
        raw = re.sub(r"^#{1,6}\s+", "", raw)
        # Quitar negritas/itálicas/backticks
        raw = re.sub(r"[*_`]+", "", raw)

        # Si la linea parece fila de tabla y no fue capturada antes, ignórala.
        if raw.startswith("|") and raw.endswith("|"):
            continue

        lineas_limpias.append(raw)

    texto = "\n".join(lineas_limpias)
    texto = re.sub(r'\n\s*\n', '\n\n', texto).strip()
    
    print("Agente 2: Guion limpio y listo.")
    return {"guion_limpio": texto}

def agente_3_productor(state: PodcastState) -> dict:
    """Agente 3: Se conecta a OpenAI y genera el MP3."""
    print("Agente 3: Grabando en el estudio (Generando audio con OpenAI)...")
    # Tomamos el texto limpio y añadimos instrucciones de voz según metadatos
    texto_a_grabar = state.get("guion_limpio", "")
    meta = state.get("meta", {})
    gender = (meta.get("voice_gender") or "").lower()
    language = (meta.get("language") or "").lower()
    accent = (meta.get("accent") or "").lower()
    tone = meta.get("tone", "")

    # No agregar metadatos al texto narrado: si se agregan, el TTS los lee literalmente.
    # Los metadatos se usan solo para logging/config de voz.

    filepath = os.environ.get("OUTPUT_FILE", "podcast_ia_generado.mp3")
    
    api_key = os.environ.get("OPENAI_API_KEY")
    
    if not api_key:
        print("⚠️ ADVERTENCIA: No se encontró OPENAI_API_KEY en las variables de entorno.")
        print("El Agente 3 creará un archivo de texto con lo que se iba a grabar para que veas el resultado del Director.")
        with open("lo_que_iba_a_grabar.txt", "w") as f:
            f.write(texto_a_grabar)
        filepath = "lo_que_iba_a_grabar.txt"
    else:
        # LLAMADA REAL A OPENAI
        client = OpenAI(api_key=api_key)
        try:
            voice = seleccionar_voz_por_genero(gender)
            print(f"Agente 3: Config voz -> voice={voice}, language={language}, accent={accent}, tone={tone}")

            response = None
            audio_guardado = False
            # Ruta recomendada por el SDK (evita warning deprecado de stream_to_file directo)
            try:
                with client.audio.speech.with_streaming_response.create(
                    model="tts-1",
                    voice=voice,
                    input=texto_a_grabar,
                ) as streamed_response:
                    streamed_response.stream_to_file(filepath)
                audio_guardado = True
            except Exception:
                # Compatibilidad con SDKs que no expongan with_streaming_response
                response = client.audio.speech.create(
                    model="tts-1",
                    voice=voice,
                    input=texto_a_grabar,
                )

            # Manejar distintos tipos de respuesta según la versión del SDK
            try:
                # Si el SDK ofrece stream_to_file
                if audio_guardado:
                    pass
                elif response is not None and hasattr(response, "stream_to_file"):
                    response.stream_to_file(filepath)
                else:
                    # Si la respuesta contiene bytes o tiene .read()
                    data = None
                    if response is not None and hasattr(response, "read"):
                        data = response.read()
                    elif isinstance(response, (bytes, bytearray)):
                        data = response

                    if data is not None:
                        # Aseguramos modo binario
                        with open(filepath, "wb") as f:
                            if isinstance(data, str):
                                f.write(data.encode("utf-8"))
                            else:
                                f.write(data)
                    else:
                        # Fallback: intentar acceder a atributo 'audio' o 'content'
                        raw = None
                        if response is not None:
                            raw = getattr(response, "audio", None) or getattr(response, "content", None)
                        if raw:
                            with open(filepath, "wb") as f:
                                if isinstance(raw, str):
                                    f.write(raw.encode("utf-8"))
                                else:
                                    f.write(raw)
                        else:
                            raise RuntimeError("Formato de respuesta de audio no reconocido por el SDK")

                print("¡Agente 3: Audio MP3 generado con éxito!")
            except Exception as write_err:
                print(f"Error al escribir el archivo de audio: {write_err}")
                filepath = ""
        except Exception as e:
            print(f"Error al conectar con OpenAI: {e}")
            filepath = ""

    # Si hay efectos en los metadatos, intentar mezclarlos (opcional).
    # Por defecto la mezcla está DESACTIVADA para mantener el flujo simple.
    # Para habilitarla, establece la variable de entorno USE_EFFECTS=1
    # o añade "use_effects": true en tu script.json.
    meta = state.get("meta", {}) or {}
    effects = meta.get("effects") or []
    use_effects_flag = os.environ.get("USE_EFFECTS", "0") == "1" or bool(meta.get("use_effects"))

    final_path = filepath
    if use_effects_flag and effects and filepath and filepath.endswith(('.mp3', '.wav')):
        try:
            from pydub import AudioSegment
        except Exception:
            print("Nota: 'pydub' no está instalado; omitiendo mezcla de efectos. Instala con: pip install pydub")
            effects = []

    if effects:
        try:
            base = AudioSegment.from_file(filepath)
            for eff in effects:
                # soportar entrada simple de cadena o dict con propiedades
                if isinstance(eff, str):
                    eff_file = eff
                    eff_meta = {}
                else:
                    eff_file = eff.get('file')
                    eff_meta = eff

                if not eff_file:
                    print(f"Efecto ignorado (sin 'file'): {eff}")
                    continue

                if not os.path.exists(eff_file):
                    print(f"Efecto no encontrado, se omite: {eff_file}")
                    continue

                seg = AudioSegment.from_file(eff_file)

                # volumen en dB (opcional)
                vol = eff_meta.get('volume')
                if isinstance(vol, (int, float)):
                    seg = seg + float(vol)

                # fades (segundos)
                fi = eff_meta.get('fade_in', 0) or 0
                fo = eff_meta.get('fade_out', 0) or 0
                if fi:
                    seg = seg.fade_in(int(fi * 1000))
                if fo:
                    seg = seg.fade_out(int(fo * 1000))

                start = eff_meta.get('start', 0) or 0
                pos_ms = int(float(start) * 1000)

                base = base.overlay(seg, position=pos_ms)

            # Guardar mezclado
            mixed_path = os.environ.get('OUTPUT_FILE', filepath)
            base.export(mixed_path, format=os.path.splitext(mixed_path)[1].lstrip('.'))
            final_path = mixed_path
            print(f"Mezcla de efectos completada: {final_path}")
        except Exception as mix_err:
            print(f"Error al mezclar efectos: {mix_err}")

    return {"mp3_filepath": final_path}

def agente_4_revisor(state: PodcastState) -> dict:
    """Agente 4: Verifica que el archivo exista y aprueba el pase a producción."""
    print("Agente 4: Control de calidad revisando los entregables...")
    filepath = state.get("mp3_filepath", "")
    
    if filepath and os.path.exists(filepath):
        estado = "Aprobado: El archivo está listo para distribución."
    else:
        estado = "Rechazado: Hubo un error en la producción del archivo."
        
    return {"estado_revision": estado}

# ==========================================
# 3. Construcción del Grafo (LangGraph)
# ==========================================
workflow = StateGraph(PodcastState)

workflow.add_node("ingesta", agente_1_ingesta)
workflow.add_node("director", agente_2_director)
workflow.add_node("productor", agente_3_productor)
workflow.add_node("revisor", agente_4_revisor)

workflow.set_entry_point("ingesta")
workflow.add_edge("ingesta", "director")
workflow.add_edge("director", "productor")
workflow.add_edge("productor", "revisor")
workflow.add_edge("revisor", END)

app = workflow.compile()

# ==========================================
# 4. Ejecución de la PoC
# ==========================================
if __name__ == "__main__":
    # Parseo de opciones: permite pasar la clave y el archivo de salida
    parser = argparse.ArgumentParser(description="Generador de podcast TTS con OpenAI")
    parser.add_argument("--api-key", help="Clave de OpenAI (opcional). Si se pasa, se establecerá en OPENAI_API_KEY.")
    parser.add_argument("--output", help="Ruta del archivo de salida (ej. episodio.mp3)." )
    parser.add_argument("--script", help="Ruta al JSON con el guion y metadatos", default="script.json")
    args = parser.parse_args()

    if args.api_key:
        os.environ["OPENAI_API_KEY"] = args.api_key
    if args.output:
        os.environ["OUTPUT_FILE"] = args.output

    # Cargar guion y metadatos desde JSON
    script_path = args.script
    mi_guion = ""
    meta = {}
    if os.path.exists(script_path):
        try:
            with open(script_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                mi_guion = data.get("script_text", "")
                meta = data
        except Exception as e:
            print(f"Error leyendo {script_path}: {e}")
    else:
        print(f"Advertencia: {script_path} no existe. Usando guion embebido por defecto.")

    if not mi_guion:
        mi_guion = """
    Título del episodio: Cómo Encontrar e Impulsar los Mejores Casos de Uso de IA en tu Organización

    Objetivo: Aprenderá a identificar y priorizar las oportunidades más valiosas para aplicar la inteligencia artificial en su negocio, desde tareas individuales hasta flujos de trabajo completos.

    Duración estimada: 2 a 3 minutos

    Guion completo:

    LOCUTOR: Hola a todos y bienvenidos a este nuevo episodio de nuestro podcast sobre estrategias de transformación digital. En esta ocasión, vamos a sumergirnos en un tema clave: cómo encontrar e impulsar los mejores casos de uso de inteligencia artificial en su organización.

    La IA se está adoptando cada vez más rápido que tecnologías anteriores como internet, y los líderes en IA están viendo incrementos significativos en su desempeño. Sin embargo, la mayoría de las empresas aún luchan por alcanzar la madurez en el uso de esta poderosa tecnología. ¿Cómo pueden ustedes aprovechar mejor el potencial de la IA?

    (SECCIÓN 1: Entender dónde aporta valor la IA)

    LOCUTOR: El primer paso es identificar aquellas áreas de su negocio que pueden beneficiarse de forma inmediata de la inteligencia artificial. Según nuestro análisis de más de 600 casos de uso, la mayoría se pueden clasificar en seis "primitivas" fundamentales: creación de contenido, automatización, investigación, codificación, análisis de datos e ideación/estrategia.

    Estas primitivas representan cientos de aplicaciones que hemos visto en diversas industrias y departamentos. Por ejemplo, en creación de contenido, la IA puede ayudar a editar y pulir borradores, generar primeros esbozos de documentos o incluso crear imágenes y visualizaciones. En análisis de datos, puede extraer insights clave de fuentes de información no estructurada. Estas son solo algunas de las maneras en que la IA puede transformar el trabajo de sus equipos.

    (SECCIÓN 2: Priorizar oportunidades de alto impacto)

    LOCUTOR: Una vez que sus equipos entiendan estas primitivas de uso de IA, el siguiente paso es recopilar y priorizar las oportunidades más prometedoras. Les recomendamos usar una matriz de impacto-esfuerzo para evaluar cada caso de uso potencial.

    Por ejemplo, automatizar la localización y optimización de contenido para múltiples canales podría ser un caso de alto impacto y bajo esfuerzo, y por lo tanto, una excelente oportunidad para empezar. En cambio, construir un asistente de IA a la medida para generar formularios web, si bien es un proyecto interesante, probablemente tenga un impacto más limitado y exija más esfuerzo.

    Al enfocarse primero en las oportunidades de alto impacto y bajo esfuerzo, podrán obtener beneficios rápidos que generen más interés e inversión en la IA.

    (SECCIÓN 3: Integrar la IA en flujos de trabajo completos)

    LOCUTOR: Pero no se queden solo en tareas aisladas. Nuestros clientes más avanzados están empezando a integrar la IA de principio a fin en sus procesos. Por ejemplo, en un flujo de trabajo de marketing, la IA podría ayudar desde la investigación de tendencias del mercado, hasta el análisis de datos, la generación de estrategias, la creación de contenido y la optimización de la distribución.

    Pensar en la IA como algo que pueden incorporar a lo largo de todo un proceso, en lugar de solo en pasos individuales, les permitirá aprovechar su poder transformador. A medida que sus equipos se familiaricen más con estas tecnologías, irán descubriendo más oportunidades de rediseñar sus flujos de trabajo.

    (SECCIÓN FINAL: Despedida)

    LOCUTOR: En resumen, para empezar a aprovechar el potencial de la IA en su organización, es clave que identifiquen las áreas que pueden beneficiarse de inmediato, enseñen a sus equipos las primitivas fundamentales de uso, y prioricen las oportunidades de mayor impacto. Y no se queden solo en tareas aisladas, sino que busquen integrar la IA a lo largo de sus procesos clave.

    Recuerden que el camino hacia la adopción y el escalamiento de la IA requiere un cambio de mentalidad, pero con los pasos adecuados, podrán liberar el verdadero poder transformador de esta tecnología. ¡Éxito en su viaje de IA!
    """
    
    initial_state = {
        "guion_crudo": mi_guion,
        "guion_limpio": "",
        "mp3_filepath": "",
        "estado_revision": "",
        "meta": meta
    }
    
    print("Iniciando Estudio de Podcast Automático...\n" + "-"*50)
    result = app.invoke(initial_state)
    
    print("-" * 50)
    print(f"Estado Final: {result['estado_revision']}")
    print(f"Entregable guardado en: {result['mp3_filepath']}")