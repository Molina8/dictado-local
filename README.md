# Dictado local

Dictado push-to-talk para Windows. Mantienes una tecla, sueltas, y el texto se pega en la ventana que tenías activa. La transcripción corre en tu máquina con faster-whisper. En ejecución no llama a internet.

El diseño se apoya en el comportamiento observable de Wispr Flow (atajo mantenido, indicador, pegado al soltar). No incluye código ni assets de ese programa. El detalle está en [docs/rea_analisis_wispr.md](docs/rea_analisis_wispr.md).

## Qué necesitas

- Windows 10 o 11
- Python 3.11
- Un micro
- Para el modelo grande, una GPU NVIDIA. Las librerías CUDA 12 van en `requirements.txt` (`cublas`, cudnn 9, runtime y nvrtc); no hace falta el toolkit de NVIDIA. Si CUDA no arranca, el programa sigue con el modelo `small` en CPU.

Probado en una RTX 5070 Ti de 16 GB.

## Instalación

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m dictado.download_model
```

`download_model` es el único paso que descarga de Hugging Face (`large-v3-turbo` y `small`). Los pesos quedan en `%LOCALAPPDATA%\dictado-local\models`.

## Uso

```powershell
.\.venv\Scripts\python -m dictado
```

Aparece un icono en la bandeja. Mantén Control derecho para grabar y suelta para transcribir y pegar. El idioma se detecta solo entre español e inglés.

La primera vez copia `config.example.yaml` a `%APPDATA%\dictado-local\config.yaml` si quieres cambiar el atajo u otra cosa. También vale `python -m dictado --config ruta\config.yaml`.

Atajos útiles en el YAML: `ctrl_r` (solo el derecho), `ctrl` (cualquiera de los dos) o `ctrl+shift`. El atajo no se traga la tecla: el sistema también la recibe.

## Pegado

Al soltar, el programa guarda el portapapeles, copia el texto, envía Ctrl+V a la ventana que estaba delante al empezar el gesto y restaura lo que había. La barra de estado no roba el foco.

Si el modelo no está descargado, la bandeja sigue abierta y el atajo no graba. El log (`%LOCALAPPDATA%\dictado-local\logs\dictado.log`) indica el comando de descarga.

## Medir una transcripción

```powershell
.\.venv\Scripts\python -m dictado.bench archivo.wav
```

Carga el modelo, calienta con silencio y cronometra el wav con los mismos ajustes que la app (haz 1, temperatura 0, VAD). El objetivo de referencia es transcribir unos 10 s de audio en menos de 1,5 s ya en caliente.

## Pruebas

```powershell
.\.venv\Scripts\python -m pytest
```

## Privacidad

Con el modelo ya en disco, el proceso fuerza `HF_HUB_OFFLINE`, `TRANSFORMERS_OFFLINE` y `HF_HUB_DISABLE_TELEMETRY`, y abre Whisper con `local_files_only=True`. No hay cuenta ni telemetría propia.
