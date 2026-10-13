# Análisis REA de Wispr Flow (referencia de diseño)

Wispr Flow sirvió solo como referencia de producto: atajo mantenido, captura de micrófono, indicador, pegado del texto y ajustes. Este documento no copia código, assets ni secretos. Las conclusiones de Electron son observaciones estáticas. Una ventana o un worker en el paquete no demuestra, por sí solo, qué hace el programa en ejecución.

## Artefacto

Instalado desde la cadena oficial (sitio wisprflow.ai, manifiesto e instalador en `dl.wisprflow.com`).

| Dato | Valor |
| --- | --- |
| Producto | Wispr Flow 1.6.1102 |
| Ejecutable | `%LOCALAPPDATA%\WisprFlow\app-1.6.1102\Wispr Flow.exe` |
| Firma | Authenticode válida. Sujeto `CN="Wispr AI, Inc."`, O=`Wispr AI, Inc.`, 444 Townsend St, San Francisco |
| Paquete | `resources\app.asar` |
| SHA-256 del asar | `5a35c867858fd0c14c643bf3530b0ba928869ff01a1383a437eb255db4969a74` |
| Ficheros en el asar | 902 |

El análisis estático usó ese `app.asar`. No se reempaquetó ni se volcó el JavaScript al repositorio.

## Llamadas REA

1. `analyze_javascript_application` sobre el `app.asar`. El resultado padre es `ev_1ebcafb9c2b8a7c3a46fff06c8cd0b595c66a996d5740038bcb548af6a90e6f4` (`parent_operation` = `analyze_javascript_application`).
2. `inspect_analysis_view` con vista `summary` sobre ese padre. Evidence `ev_1ffae3ac80831792d5ce5327202a25910886d2d0323fbcd3a8edc587648d4527`.
3. `inspect_analysis_view` con página `modules`, offset 0, límite 80. Evidence `ev_baeaba28c2f557970e528f86d97f20560b3330ec18f58a6e97ad790e26ca9f13`.
4. `inspect_analysis_view` de ítem sobre el nodo `jag_node_014abc737a47ebd2c398c9acf777c9d169a99b923da936fe7814b7891ada7d33` (`recorderWorklet.js`). Evidence `ev_7a1259743abf395cc467f6f0f7ff4b891bd73f0f66243c804a70129740339016`.
5. `inspect_analysis_view` de ítem sobre el nodo `jag_node_000558d02ea6211bcba392a943ec5b2c3ae3dfb5f8de19a960f5c39f947543c7` (`meeting_recorder/index.js`). Evidence `ev_7bdd69c00d9ad46a7116b39f0b556c5083632cf653c5d89736aa71560aac274e`.

La primera pasada chocó con metadatos de integridad de módulos nativos. La vista que se cita continuó y marcó esos bytes como no fiables (texto de limitación más abajo).

## Extractos

Vista resumen `ev_1ffae3ac80831792d5ce5327202a25910886d2d0323fbcd3a8edc587648d4527`, sujeto el asar de arriba, `normalized_result.summary`:

```text
statistics:
  relevant_files: 228
  text_bytes_read: 47156550
  parsed_javascript_files: 213
  visited_ast_nodes: 6463657
  findings: 5283
  modules: 1474
  parse_failures: 0
electron:
  browser_windows: 0
  explicit_web_preferences: 0
  preload_entrypoints: 0
  context_bridge_apis: 36
  exposed_api_members: 0
  ipc.operations: 207
  ipc.literal_channels: 10
  ipc.dynamic_channel_operations: 90
  ipc.renderer_transmissions: 180
  ipc.renderer_listeners: 27
  ipc.main_handlers: 0
  ipc.paired_renderer_transmissions: 0
  ipc.unpaired_literal_renderer_transmissions: 108
  sender_validation_observations: 13
coverage.application.status: partial
coverage.application.truncated: false
coverage.semantic.status: partial
coverage.semantic.truncated: true
javascript_analysis_semantic_result_budget_bytes: 0
limitation_count: 409
```

El presupuesto semántico del padre quedó en 0 bytes. Por eso el grafo cuenta canales y `contextBridge`, pero esta vista no lista sus nombres.

Limitaciones literales de esa misma vista (recorte):

```text
.webpack/main/index.js: The parent reserved its remaining result capacity for static observations; semantic analysis of .webpack/main/index.js was not started
.webpack/main/opusEncoder.worker.js: semantic analysis of .webpack/main/opusEncoder.worker.js was not started
.webpack/main/incrementalOpusEncoder.worker.js: semantic analysis of .webpack/main/incrementalOpusEncoder.worker.js was not started
.webpack/renderer/overlay/index.js: semantic analysis of .webpack/renderer/overlay/index.js was not started
.webpack/renderer/overlay/preload.js: semantic analysis of .webpack/renderer/overlay/preload.js was not started
.webpack/renderer/status/preload.js: semantic analysis of .webpack/renderer/status/preload.js was not started
.webpack/renderer/hub/preload.js: semantic analysis of .webpack/renderer/hub/preload.js was not started
.webpack/renderer/accessibility_drop/preload.js: semantic analysis of .webpack/renderer/accessibility_drop/preload.js was not started
.webpack/renderer/meeting_recorder/preload.js: semantic analysis of .webpack/renderer/meeting_recorder/preload.js was not started
Artifact integrity metadata contradicts observed bytes at .webpack/main/native_modules/build/Release/node_sqlite3.node; the observed bytes are untrusted.
Artifact integrity metadata contradicts observed bytes at .webpack/main/native_modules/lib/crypt32-ia32.node; the observed bytes are untrusted.
Artifact integrity metadata contradicts observed bytes at .webpack/main/native_modules/lib/crypt32-x64.node; the observed bytes are untrusted.
```

Ítem `ev_7a1259743abf395cc467f6f0f7ff4b891bd73f0f66243c804a70129740339016`:

```text
kind: javascript-asset
path: .webpack/renderer/dist/recorderWorklet.js
sha256: 3cd6c33bc2fcb35337fd1a43896fb92aa89ec3066a9d978fc02d8a5292d18d2e
observation: jag_observation_a2b6bb6d86aafedf0a118ac8d498b31d2342b1ff70f9c825014bf31ffb64aae4
properties.bytes: 1650
properties.parse_status: complete
properties.text_status: included
properties.unpacked: false
evidence.authority: artifact-bytes
evidence.state: observed
evidence.confidence: exact
```

Ítem `ev_7bdd69c00d9ad46a7116b39f0b556c5083632cf653c5d89736aa71560aac274e`:

```text
kind: javascript-asset
path: .webpack/renderer/meeting_recorder/index.js
sha256: 1fa2862331770e5b4a6cfbc88344a4880d163457d29fc4d6845804b863fbdcd3
observation: jag_observation_17b6b1f1777f402288d6accd7c478e82fabaa63c21cedf43859092b02d7c4702
static_analysis.parse_status: complete
static_analysis.visited_ast_nodes: 302603
static_analysis.references: require("electron") en línea 1, columna 1461515
static_analysis.storage: call:window.localStorage.getItem / removeItem / setItem
static_analysis.source_map_urls: index.js.map
static_analysis.vendors: webpack
static_analysis.electron.ipc: []
static_analysis.electron.context_bridge_apis: []
static_analysis.electron.browser_windows: []
```

La página de módulos `ev_baeaba28c2f557970e528f86d97f20560b3330ec18f58a6e97ad790e26ca9f13` devuelve 80 de un inventario mayor (la cobertura de la vista resumen examina 1727 de 2496 nodos y queda `complete-within-view` para esa página, no para toda la app). En esa primera página están, entre otros, `meeting_recorder/index.js` y `recorderWorklet.js`.

## Observado

Hechos estáticos, con la fuente al lado.

- El paquete es un asar de Electron. REA parseó 213 JavaScript sin fallos de parse y contó 36 APIs de `contextBridge` y 207 operaciones IPC, de las cuales 10 canales son literales y 90 son dinámicas. Cero handlers de main emparejados en el resumen, y cero transmisiones de renderer emparejadas con un handler. Eso encaja con que el análisis semántico de `.webpack/main/index.js` no llegó a arrancar: el proceso principal, que es donde vivirían los `ipcMain.handle`, quedó fuera del grafo semántico.
- Hay un worker de audio en `.webpack/renderer/dist/recorderWorklet.js` (1650 bytes, parse completo). El nombre del fichero y la ruta `renderer/dist` lo sitúan en el lado del renderer. REA no extrajo en la vista de ítem los nombres de mensajes ni el tamaño de bloque; eso no se afirma aquí.
- Existen workers llamados `opusEncoder.worker.js` e `incrementalOpusEncoder.worker.js` bajo `.webpack/main/`. Su análisis semántico no se ejecutó. Son nombres de fichero, no una prueba de que el dictado normal codifique Opus.
- `meeting_recorder/index.js` es un bundle de renderer (require de `electron`, source map, webpack) y usa `window.localStorage` para leer, borrar y escribir. Sus arrays Electron de IPC, `contextBridge` y `BrowserWindow` salieron vacíos en esa proyección.
- El inventario del asar (cabecera JSON, no REA) separa HTML de renderer para overlay, status, hub, accessibility_drop, contextMenu, feature_tour, scratchpad, meeting_recorder y meeting_ax_inspector. Cada HTML carga `../vendor/index.js` y su `index.js`. El de accessibility_drop titula la página "Accessibility". Los demás títulos de esas shells están vacíos.
- Nueve `preload.js` de renderer pesan 64738 bytes y comparten el SHA-256 `e76b8dab262e3230e2993edea73fbb4db61736b4124c8bdff9ce7ee0f5d5e4de`. Es el mismo binario reutilizado. `electron-log-preload.js` es otro fichero (1033 bytes). REA no llegó a analizar la semántica de esos preload, así que los nombres de las APIs expuestas siguen sin recuperarse. El recuento global de 36 `contextBridge` no se puede asignar a una ventana concreta.
- En el asar hay assets de audio cuyos nombres incluyen `dictation-start`, `dictation-stop` y `paste`. Solo se anotan los nombres. No se copian los wav.

## Inferido

- El producto separa superficies (overlay, estado, hub, accesibilidad, grabadora de reuniones) en `BrowserWindow` distintas, porque cada una tiene su HTML de entrada. REA reporta `browser_windows: 0` en el resumen precisamente porque la creación de ventanas estaría en el main, y ese main no tuvo análisis semántico. La inferencia viene del layout de ficheros, no de un `new BrowserWindow` observado.
- El dictado captura audio en el renderer mediante un AudioWorklet (`recorderWorklet.js`). No se recuperó el contrato de mensajes.
- La grabadora de reuniones persiste algo en `localStorage`. No se sabe qué claves.
- La ventana "Accessibility" sugiere un camino de inyección de texto distinto del portapapeles. No está demostrado.

## Desconocido

- El atajo global (si es `globalShortcut`, un hook de teclado u otra cosa), el nombre de la tecla por defecto y si el gesto es mantener o pulsar.
- Los nombres de los 10 canales IPC literales y de las 36 APIs de `contextBridge`.
- Cómo se inserta el texto en la app de delante. No hay evidencia en estas vistas de `clipboard.write` ni de una API de accesibilidad concreta. No se puede afirmar que Wispr pegue con Ctrl+V.
- Si el overlay es transparente, siempre encima, o si roba foco. El HTML existe; las preferencias de ventana no.
- Qué ajustes guarda el producto y en qué formato, más allá del `localStorage` visto en la grabadora de reuniones.
- El comportamiento en ejecución. No se trazó el proceso vivo.

Una búsqueda de literales que no encuentre nodos no prueba que la función no exista. Aquí el límite es anterior: el presupuesto semántico se agotó y los bundles grandes (main, overlay, preload, workers Opus) no entraron en el grafo de llamadas.

## Qué se llevó el diseño propio

Decisiones nuestras, no un port:

| Pieza en Wispr (observada o solo nombrada) | Decisión en dictado-local |
| --- | --- |
| Atajo global, mecanismo no recuperado | Hook con pynput, sin tragarse la tecla. Por defecto Control derecho, configurable en YAML |
| `recorderWorklet.js` en el renderer | `sounddevice`, PCM float32 mono a 16 kHz, con pre-roll si el micrófono se deja abierto |
| Workers Opus, semántica no analizada | No se usa Opus. El audio pasa en crudo a faster-whisper |
| HTML de overlay / status | Ventana Win32 pequeña, `WS_EX_NOACTIVATE` + `WS_EX_TRANSPARENT` + `WS_EX_TOPMOST` + `WS_EX_TOOLWINDOW`, para no robar el foco |
| Inyección de texto no demostrada | Al soltar: foto del portapapeles, `CF_UNICODETEXT`, Ctrl+V, restaurar. La ventana se captura al pulsar |
| `localStorage` en la grabadora de reuniones | YAML en `%APPDATA%\dictado-local\config.yaml` |
| Assets wav de dictado y pegado | Sin sonidos. El estado se ve en la barra y en el icono |
| Modelo en la nube, no analizado aquí | faster-whisper en local. `large-v3-turbo` en CUDA float16 si hay GPU; si no, `small` en CPU int8. Sin red en ejecución |

## Qué no se copió

No hay JavaScript, HTML, preload, workers, wav, iconos ni módulos nativos de Wispr en este repositorio. Los hashes de arriba identifican el artefacto analizado; no son contenido reutilizado.
