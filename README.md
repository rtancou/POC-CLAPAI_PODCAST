# PoC Podcast con OpenAI

Genera un archivo MP3 a partir de un guion definido en `script.json` usando OpenAI TTS.

## Requisitos

- Python 3.10+
- Clave OpenAI en `.env`:

```env
OPENAI_API_KEY=tu_clave
```

## Instalacion

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
```

## Configuracion del guion

Edita `script.json`:

- `title`: titulo del episodio
- `script_text`: texto narrado
- `voice_gender`: `male` o `female`
- `language`: idioma (ej. `es`)
- `accent`: acento (ej. `es-ES`, `es-MX`)
- `tone`: tono sugerido (ej. `neutral`, `calm`, `energetic`)

## Ejecucion

```bash
.venv/bin/python podcast.py --script script.json --output episodio.mp3
```

## Notas

- Los efectos de sonido quedan desactivados por defecto para mantener el flujo automatico y simple.
- Si no hay API key, se crea `lo_que_iba_a_grabar.txt` con el texto que se iba a narrar.
