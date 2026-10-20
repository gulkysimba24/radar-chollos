# Radar de chollos

Revisa Wallapop **cada 15 minutos** en 60 km alrededor de Fuenlabrada y os avisa por **Telegram** cuando sale un móvil que deja beneficio. Funciona solo en GitHub, gratis, con el ordenador apagado y sin gastar nada de Claude.

## Qué hace

- **Cualquier modelo hasta 600 €**, sobre todo iPhone. Android solo si es un chollo de verdad (60 € de beneficio sin reparar, 80 € reparando).
- **Calcula el precio de mercado solo.** Cada revisión anota lo que piden por cada modelo en buen estado en vuestra zona y usa la mediana. Así sirve para cualquier modelo y se actualiza solo cuando los precios cambian.
- **Separa en 4 apartados** dentro del grupo de Telegram:
  - 🍏 iPhone · Listos para vender (sin daños, comprar y revender: 25 € o más de beneficio)
  - 🔧 iPhone · Para reparar (reparación leve o media: 40 € o más)
  - 🤖 Android · Listos para vender
  - 🛠️ Android · Para reparar
- **Cada aviso trae**: modelo y capacidad, estado, qué hay que reparar y cuánto cuesta, precio pedido, cuánto ofrecer, precio máximo, cuánto se vende y cuánto ganas, zona y **distancia a Fuenlabrada**, cuándo se publicó y cuánta gente lo está mirando, qué preguntar, cómo regatear y un mensaje listo para copiar.
- **Botones** en cada aviso: abrir el anuncio, verlo en el mapa y cómo llegar en Google Maps.
- **Mapa** en una página web que se abre desde el móvil, con todos los chollos activos, filtros por iPhone/Android, listos/reparar y distancia.
- **Avisa si baja de precio** un anuncio que ya os mandó, y si uno que estaba un poco caro baja lo suficiente para ser chollo.
- **Marca los vendidos**: si el anuncio desaparece, el mensaje de Telegram cambia a "Ya no está a la venta".
- **Descarta solo**: bloqueados o con cuenta puesta, Face ID o huella rotos, que no encienden, mojados, pantalla sin imagen, tiendas, plegables y anuncios con pinta de estafa (solo envío, pago por adelantado).
- **Avisa del riesgo**: si un móvil está muy por debajo de su precio normal (menos del 70–80 %), el aviso lo marca con ⚠️ y añade preguntas sobre factura, financiación e IMEI. Suelen ser estafas, robados o financiados, aunque a veces es un chollo real.
- **Solo avisa si sale de verdad**: el precio pedido tiene que estar como mucho un 7 % por encima del máximo. Los que están un poco más caros (hasta un 28 %) se vigilan en silencio y, si bajan de precio, os llega el aviso.
- **Por la noche (0:00–8:00) los avisos llegan sin sonido.**

La **primera revisión** manda de golpe los chollos de las últimas horas (en la prueba fueron 18). Después llegan pocos, según van saliendo.

## Puesta en marcha (unos 20 minutos)

### 1. Bot de Telegram
1. En Telegram abre **@BotFather**, escribe `/newbot`, ponle nombre y un usuario que acabe en `bot`.
2. Guarda el **token** que te da (por ejemplo `7712345678:AAH...`). No lo compartas con nadie.

### 2. Grupo con apartados
1. Crea un grupo con tu compañero.
2. En los ajustes del grupo activa **Temas** (Topics).
3. Añade el bot al grupo y hazlo **administrador** con el permiso **Gestionar temas**.
4. Escribe "hola" en el grupo.
5. En el navegador abre `https://api.telegram.org/bot<TOKEN>/getUpdates` (cambia `<TOKEN>`). Busca `"chat":{"id":-100…`: ese número, con el signo menos, es el **chat id**.

El bot crea los 4 apartados él solo en la primera revisión.

### 3. Repositorio en GitHub
1. Crea cuenta en github.com.
2. Crea un repositorio **público** llamado `radar-chollos`. Tiene que ser público para que el mapa y los minutos de ejecución sean gratis. Lo que queda a la vista es el código y los anuncios (que ya son públicos en Wallapop); el token de Telegram va guardado aparte y nadie puede verlo.
3. Sube todos los archivos de esta carpeta, incluidas las carpetas `.github`, `data`, `docs`, `radar` y `tools` ("Add file" › "Upload files" y arrastra todo).

### 4. Claves
En el repositorio: **Settings › Secrets and variables › Actions**.
- Pestaña **Secrets** › New repository secret:
  - `TELEGRAM_TOKEN` = el token del bot
  - `TELEGRAM_CHAT_ID` = el chat id del grupo
- Pestaña **Variables** › New repository variable:
  - `MAPA_URL` = `https://TU_USUARIO.github.io/radar-chollos/` (cambia TU_USUARIO por tu usuario de GitHub)

### 5. Mapa
**Settings › Pages** › Source: "Deploy from a branch" › Branch: `main`, carpeta `/docs` › Save. En un par de minutos el mapa estará en la dirección de `MAPA_URL`. Guárdalo en la pantalla de inicio del móvil (Safari: Compartir › Añadir a pantalla de inicio).

### 6. Arrancar
**Actions** › si te pide activar los workflows, actívalos › "Radar de chollos" › **Run workflow**. Abre la ejecución: en el paso "Revisar Wallapop" debe salir algo como `412 anuncios revisados · 37 nuevos… · 2 avisos…`. Desde ahí va solo cada 15 minutos.

## Si algo falla
- **"0 anuncios revisados" o "Wallapop respondió 403"**: Wallapop bloquea las consultas desde GitHub. Alternativa: ejecutar `python3 -m radar.main` cada 15 minutos en un ordenador o Raspberry Pi siempre encendido (con `cron`), con las mismas variables de entorno.
- **Los avisos llegan al chat general y no a los apartados**: el grupo no tiene Temas activados o el bot no es administrador con "Gestionar temas". Arréglalo y borra el archivo `data/temas.json` del repositorio para que los cree.
- **No llega nada**: revisa el token, que el bot está en el grupo y que el chat id lleva el signo menos.
- **GitHub retrasa algunas revisiones** en horas punta: es normal que alguna vez pasen 20–25 minutos.

## Ajustes (archivo `radar/config.py`)
- `PRECIO_MAX` (600 €), `RADIO_KM` (60 km).
- `BENEFICIO_MIN`: beneficio mínimo por tipo.
- `IPHONE_PIEZAS` y `ANDROID_PIEZAS`: coste de cada reparación por modelo.
- `SILENCIO`: horas en las que los avisos no suenan.
- Para refrescar los precios de mercado de golpe: `python3 tools/sembrar_precios.py` (ya vienen cargados con datos del 20 de octubre de 2026).

## Límites
- El análisis es con reglas: lee el título y la descripción buscando frases como "pantalla rota", "Face ID no funciona" o "batería al 78 %". Algún fallo descrito de forma rara se puede escapar: leed siempre el anuncio entero y comprobadlo en persona (ver el checklist del estudio).
- La ubicación de Wallapop es aproximada y la distancia es en línea recta.
- Usa la API pública que usa la web de Wallapop. Si Wallapop la cambia, el radar puede dejar de funcionar hasta que se ajuste.
- Milanuncios no se incluye porque bloquea las consultas automáticas.
