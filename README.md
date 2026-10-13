# Dictado local

Dictado push-to-talk para Windows. Mantienes una tecla, sueltas, y el texto se pega en la ventana que tenías activa. La transcripción corre en tu máquina con faster-whisper. Con el modelo ya en disco no llama a internet.

El diseño se apoya en el comportamiento observable de Wispr Flow (atajo mantenido, indicador, pegado al soltar). No incluye código ni assets de ese programa. El detalle está en [docs/rea_analisis_wispr.md](docs/rea_analisis_wispr.md).

## Qué necesitas

- Windows 10 o 11
- Un micro
- Para el modelo grande, una GPU NVIDIA. El `.exe` ya lleva las librerías CUDA 12 (cublas, cuDNN 9, runtime y nvrtc). No hace falta el toolkit de NVIDIA ni tener Python instalado.
- Si CUDA no arranca, el programa sigue con el modelo `small` en CPU.

Probado en una RTX 5070 Ti de 16 GB.

La instalación desde código, para desarrollar, pide Python 3.11.

## Instalar la app (sin Python)

Hace falta el ejecutable ya generado en `dist\DictadoLocal`. En este repo se construye con:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt pyinstaller==6.16.0
.\packaging\build.ps1
```

Luego, un doble clic en `install.cmd` (o `powershell -ExecutionPolicy Bypass -File .\install.ps1`). El script:

- copia la carpeta a `%LOCALAPPDATA%\Programs\dictado-local`
- crea un acceso directo en el menú Inicio y otro en el escritorio, los dos se llaman **Dictado local**
- activa el arranque con Windows en `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` (`DictadoLocal`)
- abre la app

No pide administrador. El proceso no abre ventana de consola: se queda en la bandeja, junto al reloj. Si no ves el icono, abre la flecha de iconos ocultos.

Para abrirlo a mano: tecla Windows, escribe `Dictado local` y pulsa Enter. También vale el acceso directo del escritorio, o el ejecutable:

`%LOCALAPPDATA%\Programs\dictado-local\DictadoLocal.exe`

La primera vez, si faltan los pesos, la app los descarga de Hugging Face a `%LOCALAPPDATA%\dictado-local\models` (`large-v3-turbo` y, si hace falta el plan B, `small`). El icono se pone azul mientras descarga y verde cuando está lista. Después de eso trabaja sin red.

## Uso

Mantén Control derecho para grabar y suelta para transcribir y pegar. El idioma se detecta solo entre español e inglés. Mientras grabas sale una pastilla oscura abajo en el centro, con unas barras que suben con la voz. Al soltar pasa a unos puntos y, si el texto se pega, muestra un visto un momento. Si algo falla, un aviso breve. La pastilla no sale en la barra de tareas, no roba el foco y los clics la atraviesan. Suena un pitido corto al empezar y al soltar.

En el icono de la bandeja: estado, última frase, historial, configuración y salir.

El historial es `%LOCALAPPDATA%\dictado-local\history.jsonl` (una línea JSON por transcripción, se queda con las 2000 más nuevas).

La primera vez el instalador copia `config.example.yaml` a `%APPDATA%\dictado-local\config.yaml` si aún no existe. Desde la bandeja, "Abrir configuracion" abre ese fichero. También vale, en el modo de desarrollo, `python -m dictado --config ruta\config.yaml`.

Atajos útiles en el YAML: `ctrl_r` (solo el derecho), `ctrl` (cualquiera de los dos) o `ctrl+shift`. El atajo no se traga la tecla: el sistema también la recibe.

| Clave | Qué hace |
| --- | --- |
| `hotkey` | Atajo que hay que mantener |
| `model` | `large-v3-turbo` por defecto |
| `model_fallback` | `small` si CUDA falla |
| `device` | `auto`, `cuda` o `cpu` |
| `language` | `auto`, `es` o `en` |
| `indicator` | Pastilla de estado |
| `indicator_position` | `bottom-center` (por defecto), `bottom-left`, `bottom-right` o `top-center` |
| `indicator_monitor` | `cursor` (el monitor del ratón) o `primary` |
| `indicator_scale` | Tamaño. `1` es el normal, de `0.6` a `2` |
| `sound` | Pitidos al grabar y al soltar |
| `history` | Guardar transcripciones |
| `start_with_windows` | Al abrir el `.exe`, crea o quita la clave Run. En el modo Python no toca el registro |
| `model_dir` | Carpeta de los modelos. Vacío usa `%LOCALAPPDATA%\dictado-local\models` |

Para no arrancar con Windows, pon `start_with_windows: false`, cierra la app y ábrela otra vez.

## Pegado

Al soltar, el programa guarda el portapapeles, copia el texto, envía Ctrl+V a la ventana que estaba delante al empezar el gesto y restaura lo que había. La pastilla no roba el foco.

## Medir una transcripción

Desde el entorno de desarrollo:

```powershell
.\.venv\Scripts\python -m dictado.bench archivo.wav
```

Carga el modelo, calienta con silencio y cronometra el wav con los mismos ajustes que la app (haz 1, temperatura 0, VAD). El objetivo de referencia es transcribir unos 10 s de audio en menos de 1,5 s ya en caliente.

## Desarrollo

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m dictado.download_model
.\.venv\Scripts\python -m dictado
.\.venv\Scripts\python -m pytest
```

`download_model` es el único paso del modo desarrollo que descarga de Hugging Face. El `.exe` hace esa descarga solo si al arrancar no encuentra `model.bin`.

## Privacidad

Con el modelo ya en disco, el proceso fuerza `HF_HUB_OFFLINE`, `TRANSFORMERS_OFFLINE` y `HF_HUB_DISABLE_TELEMETRY`, y abre Whisper con `local_files_only=True`. No hay cuenta ni telemetría propia. La excepción es el primer arranque sin pesos: ahí sí descarga el modelo.
