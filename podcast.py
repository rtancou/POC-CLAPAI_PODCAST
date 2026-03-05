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

    return {"mp3_filepath": filepath}

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
        raise ValueError(
            "No se encontró contenido narrable en script.json. "
            "Define el campo 'script_text' con el guion a narrar."
        )
    
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