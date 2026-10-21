"""Una revisión completa del radar: buscar, analizar, avisar, vigilar y publicar el mapa."""
import html
import json
import os
import re
import statistics
import sys
import time
import urllib.parse
from datetime import datetime
from zoneinfo import ZoneInfo

import analisis, config, mercado, milanuncios, telegram, wallapop

RAIZ = os.path.dirname(os.path.abspath(__file__))
DATOS = RAIZ   # todo va en la carpeta principal del repositorio
WEB = RAIZ
MADRID = ZoneInfo('Europe/Madrid')
CONDICION = {'new': 'nuevo', 'as_good_as_new': 'como nuevo', 'good': 'buen estado',
             'fair': 'aceptable', 'has_given_it_all': 'lo ha dado todo'}


def cargar(nombre, defecto):
    try:
        with open(os.path.join(DATOS, nombre)) as f:
            return json.load(f)
    except Exception:
        return defecto


def guardar(nombre, datos, carpeta=DATOS):
    os.makedirs(carpeta, exist_ok=True)
    tmp = os.path.join(carpeta, nombre + '.tmp')
    with open(tmp, 'w') as f:
        json.dump(datos, f, ensure_ascii=False, separators=(',', ':'))
    os.replace(tmp, os.path.join(carpeta, nombre))


def ahora_ms():
    return int(time.time() * 1000)


def hace(ms):
    if not ms:
        return ''
    m = max(1, round((ahora_ms() - ms) / 60000))
    if m < 60:
        return f'hace {m} min'
    h = round(m / 60)
    return f'hace {h} h' if h < 48 else f'hace {round(h / 24)} días'


# ------------------------------------------------------------------ referencia de precios
def anotar_precio(precios, nombre, item_id, precio, cap):
    lista = precios.setdefault(nombre, [])
    if any(x[0] == item_id for x in lista):
        return
    lista.append([item_id, precio, ahora_ms(), cap])
    corte = ahora_ms() - 45 * 86400000
    precios[nombre] = [x for x in lista if x[2] >= corte][-150:]


def detalle(item_id):
    """Ficha completa del anuncio, venga de Wallapop o de Milanuncios."""
    return (milanuncios.detalle if str(item_id).startswith('ma-') else wallapop.detalle)(item_id)


VENTAS = []          # ventas vistas por la memoria del mercado (se cargan en ejecutar)


def pedidos(precios, nombre, cap):
    """Cuartiles de lo que piden los anuncios sin daños (plan B mientras no hay ventas reales)."""
    lista = precios.get(nombre, [])
    misma = sorted(x[1] for x in lista if cap and x[3] == cap)
    todos = sorted(x[1] for x in lista)
    ps = misma if len(misma) >= 6 else todos if len(todos) >= 4 else None
    if not ps:
        return None
    return mercado._q(ps, .25), statistics.median(ps), mercado._q(ps, .75), len(ps)


def poner_venta(a, precios):
    """Precio y rango de venta para este anuncio, según su estado (batería, marcas, caja).

    Usa las ventas reales vistas si hay bastantes; si no, lo que piden otros anuncios con descuento."""
    est = a['est']
    f = mercado.factor(a.get('bateria'), est['averias'], est.get('marcas'), re.search(r'\bcaja\b|factura', a.get('descripcion') or '', re.I))
    a['factor_estado'] = round(f, 3)
    r = mercado.rango(VENTAS, a['modelo'], a.get('capacidad'))
    if r:
        k = 0.97 * f                                      # un poco menos: el último precio suele regatearse
        a['venta_real'], a['venta_baja'], a['venta_alta'] = r['media'] * k, r['baja'] * k, r['alta'] * k
        a['fuente_venta'] = f"{r['n']} ventas reales" + ('' if r['cap'] or not a.get('capacidad') else ', todas las capacidades')
        a['fiabilidad'] = r['fiab']
    else:
        q = pedidos(precios, a['modelo'], a.get('capacidad'))
        if q:
            k = config.VENTA_FACTOR * f
            a['venta_real'], a['venta_baja'], a['venta_alta'] = q[1] * k, q[0] * k, q[2] * k
            a['fuente_venta'] = f'{q[3]} anuncios a la venta, aún sin ventas reales'
        else:
            a['venta_real'] = a['venta_baja'] = a['venta_alta'] = a['fuente_venta'] = None
        a['fiabilidad'] = 'baja'
    d, nd = mercado.dias_venta(VENTAS, a['modelo'])
    a['dias_venta'] = d
    a['dias_venta_n'] = nd


def evaluar(a, ref):
    """analisis.evaluar + los tres niveles de compra (bueno / máximo / límite) y el rango de venta."""
    v, d = analisis.evaluar(a, ref)
    if d:
        tramos(a, d)
    return v, d


def tramos(a, d):
    aj = getattr(config, 'AJUSTE_VENTA', 1.0)
    fijo = config.COSTE_FIJO[d['tipo']]
    objetivo = config.BENEFICIO_MIN[(a['familia'], d['tipo'])]
    coste = d['coste_reparacion']
    baja = (a.get('venta_baja') or d['venta'] / aj * 0.92) * aj
    alta = (a.get('venta_alta') or d['venta'] / aj * 1.06) * aj
    d['venta_rango'] = [round(baja), round(alta)]
    d['precio_bueno'] = analisis._r5(baja - coste - fijo - objetivo)
    d['limite'] = analisis._r5(d['venta'] - coste - fijo)
    d['fiabilidad'] = a.get('fiabilidad', 'baja')
    d['factor_estado'] = a.get('factor_estado')
    d['fuente_venta'] = a.get('fuente_venta')


def estimar_venta(precios, nombre, cap):
    """Lo que el bot cree que se vende un modelo funcionando (sin el ajuste aprendido)."""
    v, _ = mercado.venta_real(VENTAS, nombre, cap)
    if v:
        return v * 0.97
    ref = referencia(precios, nombre, cap)
    return ref * config.VENTA_FACTOR if ref else None


def referencia(precios, nombre, cap):
    lista = precios.get(nombre, [])
    if cap:
        misma = [x[1] for x in lista if x[3] == cap]
        m = analisis.mediana(misma, 6)
        if m:
            return m
    return analisis.mediana([x[1] for x in lista], 4)


# ------------------------------------------------------------------ mensajes
def tema_de(a):
    return f"{a['familia']}_{a['eval']['tipo']}"


def botones(a):
    filas = [[{'text': '📲 Abrir anuncio', 'url': a['url']}]]
    fila2 = []
    mapa = os.environ.get('MAPA_URL')
    if mapa:
        fila2.append({'text': '🗺️ Ver en el mapa', 'url': f"{mapa.rstrip('/')}/#{a['id']}"})
    if a.get('lat') is not None:
        destino = f"{a['lat']:.5f},{a['lng']:.5f}"
        fila2.append({'text': '🚗 Cómo llegar', 'url': 'https://www.google.com/maps/dir/?api=1&' + urllib.parse.urlencode(
            {'origin': f'{config.ORIGEN_NOMBRE}, Madrid', 'destination': destino, 'travelmode': 'driving'})})
    if fila2:
        filas.append(fila2)
    return filas


def texto_aviso(a, cabecera=None):
    e, d = html.escape, a['eval']
    icono = '🍏' if a['familia'] == 'iphone' else '🤖'
    titulo = f"{icono} <b>{e(a['modelo'])}</b>" + (f" · {e(a['capacidad'])}" if a.get('capacidad') else '')
    if d['tipo'] == 'listo':
        tipo = '✅ Listo para comprar y vender'
    else:
        tipo = f"🔧 Reparación {d['nivel']}: {e(', '.join(d['reparacion']))}"
    if d.get('precio_bueno') is not None and a['precio'] <= d['precio_bueno']:
        ya = '✅ Ya está en buen precio: ganas aunque lo vendas barato'
    elif a['precio'] <= d['max_pagar']:
        ya = '⚡ Ya está por debajo del máximo'
    else:
        ya = '🤝 Hay que regatear para que salga'
    riesgo = {
        'alto': f"⚠️ <b>Muy barato ({d.get('pct_mercado')} % del precio normal).</b> Puede ser estafa, robado, financiado o tener algo oculto. "
                "Pide factura y comprueba el IMEI antes de ir. Nunca pagues por adelantado.",
        'medio': f"⚠️ Bastante por debajo de mercado ({d.get('pct_mercado')} %). Pide factura y comprueba el IMEI.",
    }.get(d.get('riesgo'))
    ben = d['beneficio_precio_pedido']
    lineas = []
    if cabecera:
        lineas += [cabecera, '']
    cat = {'chollazo': '🔥🔥 <b>CHOLLAZO · compra ya</b>', 'bueno': '💚 <b>Chollo bueno</b>',
           'normal': '🔵 Chollo normal',
           'regatear': f"🤝 <b>Para regatear</b>: piden un {round((a['precio'] / max(d['max_pagar'], 1) - 1) * 100)} % más que el máximo",
           'trampa': f"🟣 <b>¿TRAMPA?</b> {e(d.get('motivo_trampa') or '')}. Puede ser estafa o tener algo oculto, aunque a veces es un chollo real."
           }.get(d.get('categoria'), '🔵 Chollo normal')
    if d.get('categoria') == 'trampa':
        riesgo = 'Pide factura y foto del IMEI en Ajustes antes de quedar. Nunca pagues ni envíes nada por adelantado.'
    extra = []
    if a.get('origen') == 'milanuncios':
        extra.append('📰 Anuncio de <b>Milanuncios</b> (ubicación aproximada: solo el pueblo)')
    if a.get('tienda'):
        extra.append('🏪 Perfil destacado: puede ser un revendedor, pregunta si da factura')
    if a['est'].get('reacondicionado'):
        extra.append('♻️ Dice «reacondicionado»: pregunta dónde se compró y si conserva la garantía')
    if a['est'].get('supuesto'):
        extra.append('❓ Dice que está roto pero no qué: se calcula como si fuera la pantalla')
    lineas += [cat, titulo, tipo] + ([riesgo] if riesgo else []) + extra + [
        '',
        f"💶 Piden <b>{a['precio']:.0f} €</b> → ofrece <b>{d['oferta']} €</b> · máximo <b>{d['max_pagar']} €</b>",
        f"📈 Se vende por ~{d['venta']} € · ganas <b>{'+' if d['beneficio_oferta'] > 0 else ''}{d['beneficio_oferta']} €</b> con tu oferta"
        f" ({'+' if ben > 0 else ''}{ben} € pagando lo que piden)",
        ya,
    ] + tramos_txt(d) + ([f"⏱️ Este modelo se suele vender en <b>~{str(a['dias_venta']).replace('.', ',')} días</b> ({a['dias_venta_n']} ventas vistas)"]
         if a.get('dias_venta') is not None else []) + [
        f"📍 {e(a.get('zona') or 'Madrid')} · <b>~{a['km']} km</b> de {config.ORIGEN_NOMBRE}" if a.get('km') is not None
        else f"📍 {e(a.get('zona') or 'Madrid')}",
        f"🔎 {e(a['resumen'])}",
    ]
    cont = a.get('contadores') or {}
    actividad = f"🕒 Publicado {hace(a.get('publicado_ms'))}" if a.get('publicado_ms') else '🕒'
    if cont:
        actividad += f" · 👀 {cont.get('views', 0)} visitas · ❤️ {cont.get('favorites', 0)} · 💬 {cont.get('conversations', 0)} chats"
    lineas += [actividad, '', '<b>Pregunta antes de ir:</b>']
    lineas += [f'• {e(p)}' for p in a['preguntas']]
    lineas += ['', f"<b>Regateo:</b> {e(a['regateo'])}", '', '<b>Mensaje para copiar:</b>', f"<code>{e(a['mensaje'])}</code>"]
    return '\n'.join(lineas)


FIAB = {'alta': '🟢 fiabilidad alta', 'media': '🟡 fiabilidad media', 'baja': '🟠 fiabilidad baja'}


def tramos_txt(d):
    if 'precio_bueno' not in d:
        return []
    if d['precio_bueno'] < d['max_pagar']:
        l = [f"🎯 Compra: 🟢 buen precio ≤ <b>{d['precio_bueno']} €</b> · 🟡 máximo {d['max_pagar']} € · 🔴 nunca más de {d['limite']} €"]
    else:
        l = [f"🎯 Compra: 🟢 hasta <b>{d['max_pagar']} €</b> · 🔴 nunca más de {d['limite']} €"]
    if d.get('venta_rango'):
        l.append(f"💰 Se vende entre <b>{d['venta_rango'][0]} y {d['venta_rango'][1]} €</b> · {FIAB.get(d.get('fiabilidad'), '')}"
                 + (f" ({html.escape(d['fuente_venta'])})" if d.get('fuente_venta') else ''))
    return l


def silencio():
    h = datetime.now(MADRID).hour
    ini, fin = config.SILENCIO
    return ini <= h < fin


# ------------------------------------------------------------------ revisión
def preparar(item):
    """Datos básicos de un anuncio de la búsqueda, o None si no es un móvil que tratemos."""
    titulo = item.get('title') or ''
    if analisis.es_accesorio(titulo):
        return None
    m = analisis.modelo(titulo)
    if not m:
        return None
    if wallapop.flag(item.get('reserved')) or wallapop.flag(item.get('is_refurbished')) or wallapop.flag(item.get('has_warranty')):
        return None
    desc = item.get('description') or ''
    loc = item.get('location') or {}
    texto = f'{titulo} {desc}'
    return {
        'id': item['id'], 'familia': m[0], 'modelo': m[1], 'gama': m[2], 'titulo': titulo, 'descripcion': desc[:2000],
        'precio': float(item['price']['amount']), 'capacidad': analisis.capacidad(texto), 'bateria': analisis.bateria(texto),
        'zona': loc.get('city'), 'lat': loc.get('latitude'), 'lng': loc.get('longitude'),
        'km': analisis.km(loc.get('latitude'), loc.get('longitude')),
        'url': item.get('url') or f"https://es.wallapop.com/item/{item.get('web_slug')}", 'publicado_ms': item.get('created_at'),
        'origen': item.get('origen', 'wallapop'),
        'tienda': wallapop.flag(item.get('is_top_profile')),
        'est': analisis.estado(titulo, desc),
        'foto': (((item.get('images') or [{}])[0].get('urls') or {}).get('medium')),
    }


def completar(a):
    """Añade datos de la ficha completa: estado según Wallapop, capacidad, visitas."""
    det = detalle(a['id'])
    if det is None:
        return False
    if isinstance(det, dict):
        ta = det.get('type_attributes') or {}
        cond = (ta.get('condition') or {}).get('value')
        a['condicion'] = CONDICION.get(cond, '')
        cap = (ta.get('storage_capacity') or {}).get('text')
        if cap and not a.get('capacidad'):
            a['capacidad'] = cap
        a['contadores'] = det.get('counters') or {}
        if cond == 'has_given_it_all' and a['eval']['tipo'] == 'listo':
            return False               # el propio vendedor dice que está muy gastado
    return True


def ficha_web(a, estado='activo'):
    d = a['eval']
    return {
        'id': a['id'], 'familia': a['familia'], 'tipo': d['tipo'], 'nivel': d['nivel'], 'modelo': a['modelo'],
        'capacidad': a.get('capacidad'), 'precio': a['precio'], 'oferta': d['oferta'], 'max': d['max_pagar'],
        'venta': d['venta'], 'beneficio': d['beneficio_oferta'], 'reparacion': d['reparacion'],
        'zona': a.get('zona'), 'km': a.get('km'), 'lat': a.get('lat'), 'lng': a.get('lng'), 'url': a['url'],
        'resumen': a['resumen'], 'preguntas': a['preguntas'], 'regateo': a['regateo'], 'mensaje': a['mensaje'],
        'publicado_ms': a.get('publicado_ms'), 'avisado_ms': a.get('avisado_ms'), 'estado': estado,
        'riesgo': d.get('riesgo'), 'pct_mercado': d.get('pct_mercado'), 'categoria': d.get('categoria'),
        'motivo_trampa': d.get('motivo_trampa'), 'foto': a.get('foto'), 'bateria': a.get('bateria'),
        'dias_venta': a.get('dias_venta'), 'fuente_venta': d.get('fuente_venta'), 'coste_reparacion': d.get('coste_reparacion'),
        'origen': a.get('origen', 'wallapop'), 'profesional': bool(a.get('tienda')),
        'reservado': bool(a.get('reservado')), 'precio_bueno': d.get('precio_bueno'), 'limite': d.get('limite'), 'venta_rango': d.get('venta_rango'),
        'fiabilidad': d.get('fiabilidad'), 'factor_estado': d.get('factor_estado'),
        'precio_inicial': a.get('precio_inicial', a['precio']),
    }


DESCARTADOS = set()   # anuncios que habéis marcado «No me interesa» en la web


def interesa(a, d=None):
    """False si es algo que ahora no queréis ver: descartado, o iPhone roto que no sea una ganga."""
    d = d or a.get('eval') or {}
    if a['id'] in DESCARTADOS:
        return False
    if (getattr(config, 'SOLO_ROTOS_CHOLLAZO', False) and a.get('familia') == 'iphone'
            and d.get('tipo') == 'reparar' and d.get('categoria') != 'chollazo'):
        return False
    return True


def avisar(a, temas, activos, cabecera=None):
    a['resumen'], a['preguntas'], a['regateo'], a['mensaje'] = analisis.textos(a)
    a['avisado_ms'] = ahora_ms()
    callado = silencio() or a['eval'].get('categoria') == 'regatear'
    if a.get('publicado_ms') and a['publicado_ms'] < ahora_ms() - 48 * 3600000 and not cabecera:
        # anuncio de hace días que el bot no había visto (búsqueda nueva o Milanuncios): al mapa, sin aviso
        a['msg_id'] = None
        activos[a['id']] = {k: v for k, v in a.items() if k != 'est'} | {'est': a['est']}
        return True
    msg = telegram.enviar(texto_aviso(a, cabecera), temas.get(tema_de(a)), botones(a), silencioso=callado, foto=a.get('foto'),
                          clave=tema_de(a))
    if msg is None:
        return False
    a['msg_id'] = msg
    activos[a['id']] = {k: v for k, v in a.items() if k != 'est'} | {'est': a['est']}
    return True


def revisar_conocidos(activos, vigilar, temas, precios):
    """Comprueba si los chollos avisados siguen a la venta o han bajado, y si alguno vigilado ya es chollo."""
    avisos = 0
    limite = ahora_ms() - config.DIAS_ACTIVO * 86400000
    pendientes = sorted([a for a in activos.values() if a.get('estado', 'activo') == 'activo' and a['avisado_ms'] >= limite],
                        key=lambda a: a.get('revisado_ms', 0))[:80]
    for a in pendientes:
        det = detalle(a['id'])
        a['revisado_ms'] = ahora_ms()
        if det == 'error':
            continue
        if det is None or wallapop.flag(det.get('sold')):
            a['estado'] = 'vendido'
            telegram.editar(a.get('msg_id'), '❌ <b>Ya no está a la venta</b> (vendido o retirado)\n\n' + texto_aviso(a), foto=a.get('foto'))
            continue
        a['reservado'] = wallapop.flag(det.get('reserved'))
        nuevo = float(((det.get('price') or {}).get('cash') or {}).get('amount') or a['precio'])
        if nuevo < a['precio'] - 0.5:
            antes = a['precio']
            a.setdefault('precio_inicial', antes)
            a['precio'] = nuevo
            ref = referencia(precios, a['modelo'], a.get('capacidad'))
            poner_venta(a, precios)
            v, d = evaluar(a, ref or a['eval']['ref_mercado'])
            if d:
                a['eval'] = d
            a['resumen'], a['preguntas'], a['regateo'], a['mensaje'] = analisis.textos(a)
            telegram.editar(a.get('msg_id'), f'📉 <b>Ha bajado de {antes:.0f} € a {nuevo:.0f} €</b>\n\n' + texto_aviso(a), botones(a), foto=a.get('foto'))
            if a['id'] not in DESCARTADOS:
                telegram.responder(a.get('msg_id'), f'📉 {html.escape(a["modelo"])} ha bajado a <b>{nuevo:.0f} €</b>',
                                   temas.get(tema_de(a)), clave=tema_de(a))
            avisos += 1
        time.sleep(0.4)

    for vid, a in sorted(vigilar.items(), key=lambda kv: kv[1].get('revisado_ms', 0))[:60]:
        det = detalle(vid)
        a['revisado_ms'] = ahora_ms()
        if det is None or (isinstance(det, dict) and wallapop.flag(det.get('sold'))) or a['avisado_ms_vigilar'] < ahora_ms() - 10 * 86400000:
            vigilar.pop(vid, None)
            continue
        if det == 'error':
            continue
        nuevo = float(((det.get('price') or {}).get('cash') or {}).get('amount') or a['precio'])
        if nuevo < a['precio'] - 0.5:
            antes = a['precio']
            a['precio'] = nuevo
            ref = referencia(precios, a['modelo'], a.get('capacidad')) or a.get('ref')
            poner_venta(a, precios)
            veredicto, d = evaluar(a, ref)
            if veredicto == 'avisar':
                a['eval'] = d
                a['precio_inicial'] = antes
                if completar(a) and avisar(a, temas, activos, cabecera=f'📉 <b>Ha bajado de {antes:.0f} € a {nuevo:.0f} €</b>'):
                    avisos += 1
                vigilar.pop(vid, None)
        time.sleep(0.4)
    return avisos


def exportar(activos, vigilados=None):
    limite = ahora_ms() - config.DIAS_ACTIVO * 86400000
    lista = []
    for a in activos.values():
        if a['avisado_ms'] < limite:
            continue
        if a.get('estado') == 'vendido' and a.get('revisado_ms', 0) < ahora_ms() - 86400000:
            continue
        if not interesa(a):
            continue
        lista.append(ficha_web(a, a.get('estado', 'activo')))
    for a in (vigilados or {}).values():           # casi chollos que el bot vigila: en el mapa como «para regatear»
        if a.get('avisado_ms_vigilar', 0) < limite or not a.get('eval') or a['id'] in activos or not interesa(a):
            continue
        if 'resumen' not in a:
            a['resumen'], a['preguntas'], a['regateo'], a['mensaje'] = analisis.textos(a)
        a.setdefault('avisado_ms', a['avisado_ms_vigilar'])
        f = ficha_web(a)
        if f['categoria'] != 'trampa':
            f['categoria'] = 'regatear'
        f['vigilado'] = True
        lista.append(f)
    lista.sort(key=lambda x: -x['avisado_ms'])
    guardar('chollos.json', {'actualizado_ms': ahora_ms(), 'origen': {'nombre': config.ORIGEN_NOMBRE, 'lat': config.ORIGEN[0], 'lng': config.ORIGEN[1]},
                             'chollos': lista}, carpeta=WEB)


# ------------------------------------------------------------------ guardados y registro (lo que escribe la web)
def item_de_detalle(det):
    """Convierte la ficha completa de Wallapop al formato de la búsqueda, para analizarla igual."""
    txt = lambda v: (v or {}).get('original') if isinstance(v, dict) else (v or '')
    return {
        'id': det['id'], 'title': txt(det.get('title')), 'description': txt(det.get('description')),
        'price': {'amount': ((det.get('price') or {}).get('cash') or {}).get('amount') or 0},
        'images': det.get('images'), 'location': det.get('location'), 'web_slug': det.get('slug'),
        'reserved': det.get('reserved'), 'is_top_profile': (det.get('user') or {}).get('is_top_profile'),
        'url': det.get('url'), 'origen': 'milanuncios' if str(det.get('id', '')).startswith('ma-') else 'wallapop',
    }


def id_de_enlace(url):
    """Saca el id interno de Wallapop de un enlace tipo https://es.wallapop.com/item/iphone-13-...-1234567890."""
    ma = re.search(r'milanuncios\.com/.*?-(\d{6,})\.htm', url or '')
    if ma:
        return 'ma-' + ma.group(1)
    m = re.search(r'/item/([a-z0-9-]+)', url or '')
    if not m:
        return None
    slug = m.group(1)
    code, body = wallapop._get(f'https://es.wallapop.com/item/{slug}')
    if code == 200:
        m2 = re.search(r'"id":"([a-z0-9]{10,14})"', body)
        if m2:
            return m2.group(1)
    # Plan B (la web de Wallapop a veces bloquea a GitHub): buscarlo por el título con la API
    num = slug.rsplit('-', 1)[-1]
    trozos = [w for w in slug.split('-')[:-1] if w]
    for palabras, orden in ((' '.join(trozos), 'most_relevance'), (' '.join(trozos[:4]), 'most_relevance'),
                            (' '.join(trozos), 'newest'), (' '.join(trozos[:3]), 'most_relevance')):
        if not palabras:
            continue
        for it in wallapop.buscar(palabras[:60], 3, radio_km=400, orden=orden, precio_max=100000):
            urls = ' '.join((im.get('urls') or {}).get('small', '') for im in it.get('images') or [])
            if it.get('web_slug') == slug or (num.isdigit() and f'p{num}/' in urls):
                return it['id']
    return None


def valorar(a, precios):
    """Análisis de un anuncio que habéis guardado vosotros, aunque el bot no lo vea chollo."""
    ref = referencia(precios, a['modelo'], a.get('capacidad'))
    poner_venta(a, precios)
    if not ref and not a.get('venta_real'):
        return None
    v, d = evaluar(a, ref or a['venta_real'] / config.VENTA_FACTOR)
    if d:
        return d
    est = a['est']
    tipo = 'reparar' if (est['averias'] or est['extras']) else 'listo'
    c = analisis.costes(a['familia'], a['modelo'], a['gama'], est) if tipo == 'reparar' else (0, None, [])
    coste, nivel, detalle = c or (0, None, ['reparación difícil de calcular'])
    if est['grave']:
        detalle = list(detalle) + ['⚠️ ojo: ' + ', '.join(est['grave'])]
    venta = (a.get('venta_real') or ref * config.VENTA_FACTOR) * getattr(config, 'AJUSTE_VENTA', 1.0)
    fijo, objetivo = config.COSTE_FIJO[tipo], config.BENEFICIO_MIN[(a['familia'], tipo)]
    maxp = venta - coste - fijo - objetivo
    oferta = max(0, min(analisis._r5(a['precio'] * 0.85), analisis._r5(maxp)))
    d = {'riesgo': 'bajo', 'pct_mercado': round(a['precio'] / ref * 100) if ref else None, 'categoria': 'normal',
            'motivo_trampa': None, 'fuente_venta': a.get('fuente_venta'), 'tipo': tipo, 'nivel': nivel, 'reparacion': detalle,
            'coste_reparacion': round(coste), 'ref_mercado': round(ref or 0), 'venta': round(venta),
            'max_pagar': round(maxp), 'oferta': oferta,
            'beneficio_precio_pedido': round(venta - a['precio'] - coste - fijo),
            'beneficio_oferta': round(venta - oferta - coste - fijo)}
    tramos(a, d)
    return d


def analizar_guardado(wid, precios):
    det = detalle(wid)
    if det is None:
        return {'estado': 'vendido', 'revisado_ms': ahora_ms()}
    if not isinstance(det, dict):
        return None
    a = preparar(item_de_detalle(det)) if analisis.modelo(item_de_detalle(det)['title']) else None
    if not a:
        it = item_de_detalle(det)
        return {'estado': 'activo', 'wid': wid, 'titulo': it['title'], 'precio': float(it['price']['amount']),
                'url': f"https://es.wallapop.com/item/{it['web_slug']}", 'revisado_ms': ahora_ms(),
                'foto': ((it.get('images') or [{}])[0].get('urls') or {}).get('medium')}
    a['contadores'] = det.get('counters') or {}
    d = valorar(a, precios)
    info = {'estado': 'vendido' if wallapop.flag(det.get('sold')) else 'activo', 'wid': wid, 'revisado_ms': ahora_ms()}
    if d:
        a['eval'] = d
        a['resumen'], a['preguntas'], a['regateo'], a['mensaje'] = analisis.textos(a)
        info['ficha'] = ficha_web(a)
    else:
        info.update({'titulo': a['titulo'], 'precio': a['precio'], 'url': a['url'], 'foto': a.get('foto')})
    return info


def nombre_guardado(g, info):
    f = (info or {}).get('ficha') or g
    return f.get('modelo') or (info or {}).get('titulo') or 'un anuncio'


def procesar_web(temas, activos, precios, revisar_estado=False):
    """Avisa en Telegram de lo nuevo que habéis guardado o apuntado en el registro desde la web."""
    guardados = cargar('guardados.json', {}).get('items', {})
    registro = cargar('registro.json', {})
    info = cargar('guardados_info.json', {})
    est = cargar('estado_web.json', {})
    est.setdefault('guardados', [])
    est.setdefault('compras', {})
    tema = temas.get('equipo')
    mapa = (os.environ.get('MAPA_URL') or '').rstrip('/')
    e = html.escape

    for gid, g in guardados.items():
        if gid in est['guardados']:
            continue
        wid = g.get('wid') or (gid if gid in activos else None)
        if not wid and g.get('url'):
            wid = id_de_enlace(g['url'])
        if wid:
            nuevo = analizar_guardado(wid, precios)
            if nuevo:
                info[gid] = nuevo
        i = info.get(gid) or {}
        f = i.get('ficha') or g
        precio = f.get('precio') or i.get('precio')
        lineas = [f"⭐ <b>{e(g.get('por') or 'Alguien')}</b> ha guardado <b>{e(nombre_guardado(g, i))}</b>"
                  + (f" · {precio:.0f} €" if precio else '')]
        if f.get('max') is not None:
            lineas.append(f"Ofrece {f.get('oferta')} € · máximo {f.get('max')} € · ganas ~{f.get('beneficio')} €")
        if f.get('zona'):
            lineas.append(f"📍 {e(f['zona'])}" + (f" · ~{f['km']} km" if f.get('km') is not None else ''))
        if g.get('nota'):
            lineas.append(f"📝 {e(g['nota'])}")
        if not wid:
            lineas.append('No he podido abrir el enlace todavía; lo vuelvo a intentar en la próxima pasada.')
            info[gid] = {'error': 'No he podido abrir el anuncio todavía. Lo vuelvo a intentar en la próxima pasada.',
                         'intentos': 1, 'revisado_ms': ahora_ms(), 'url': g.get('url')}
        url = f.get('url') or i.get('url') or g.get('url')
        bot = [[{'text': '📲 Abrir anuncio', 'url': url}]] if url else []
        if mapa:
            bot.append([{'text': '⭐ Ver guardados', 'url': f'{mapa}/#guardados'}])
        telegram.enviar('\n'.join(lineas), tema, bot or None, foto=f.get('foto') or i.get('foto'))
        est['guardados'].append(gid)

    # enlaces que no se pudieron abrir: se reintenta en las siguientes pasadas
    for gid, g in guardados.items():
        i = info.get(gid)
        if gid not in est['guardados'] or (i and not i.get('error')) or (i or {}).get('intentos', 0) >= 6:
            continue
        wid = g.get('wid') or (id_de_enlace(g['url']) if g.get('url') else None)
        nuevo = analizar_guardado(wid, precios) if wid else None
        if nuevo:
            info[gid] = nuevo
            f = nuevo.get('ficha') or {}
            telegram.enviar(f"🔎 Ya he analizado el guardado de {e(g.get('por') or 'alguien')}: <b>{e(nombre_guardado(g, nuevo))}</b>"
                            + (f" · {f['precio']:.0f} € → máximo {f.get('max')} €, ganas ~{f.get('beneficio')} €" if f.get('precio') else ''),
                            tema, [[{'text': '⭐ Ver guardados', 'url': f'{mapa}/#guardados'}]] if mapa else None)
        else:
            info[gid] = {'error': 'No he podido abrir el anuncio (puede que lo hayan quitado). Lo vuelvo a intentar en la próxima pasada.',
                         'intentos': (i or {}).get('intentos', 0) + 1, 'revisado_ms': ahora_ms(), 'url': g.get('url')}

    for gid in list(info):
        if gid not in guardados:
            info.pop(gid)
    est['guardados'] = [g for g in est['guardados'] if g in guardados]

    if revisar_estado:            # ¿alguno guardado se ha vendido o ha bajado?
        pend = sorted([(gid, i) for gid, i in info.items() if i.get('wid') and i.get('estado') == 'activo'],
                      key=lambda kv: kv[1].get('revisado_ms', 0))[:25]
        for gid, i in pend:
            det = detalle(i['wid'])
            i['revisado_ms'] = ahora_ms()
            nombre = e(nombre_guardado(guardados.get(gid, {}), i))
            if det is None or (isinstance(det, dict) and wallapop.flag(det.get('sold'))):
                i['estado'] = 'vendido'
                telegram.enviar(f'❌ Un guardado ya no está a la venta: <b>{nombre}</b>', tema)
            elif isinstance(det, dict):
                p = float(((det.get('price') or {}).get('cash') or {}).get('amount') or 0)
                antes = (i.get('ficha') or {}).get('precio') or i.get('precio')
                if p and antes and p < antes - 0.5:
                    i.update(analizar_guardado(i['wid'], precios) or {})
                    i['bajada_de'] = antes
                    f = i.get('ficha') or {}
                    telegram.enviar(f'📉 Un guardado ha bajado: <b>{nombre}</b> de {antes:.0f} € a <b>{p:.0f} €</b>'
                                    + (f" · ahora ganarías ~{f.get('beneficio')} €" if f.get('beneficio') is not None else ''), tema)
            time.sleep(0.3)

    for c in registro.get('compras', []):
        cid = c.get('id')
        if not cid:
            continue
        ahora = 'vendido' if c.get('precio_venta') not in (None, '') else 'comprado'
        if est['compras'].get(cid) == ahora:
            continue
        quien = e(c.get('quien') or '')
        modelo = e(c.get('modelo') or 'móvil') + (f" {e(c['capacidad'])}" if c.get('capacidad') else '')
        rep = sum(float(r.get('coste') or 0) for r in c.get('reparaciones') or [])
        coste = float(c.get('precio_compra') or 0) + rep + float(c.get('gasolina') or 0) + float(c.get('otros') or 0)
        if ahora == 'comprado':
            txt = f"🛒 <b>Compra apuntada</b>{' por ' + quien if quien else ''}: {modelo} por <b>{float(c.get('precio_compra') or 0):.0f} €</b>"
            if rep:
                txt += f" + {rep:.0f} € de reparación"
        else:
            ben = float(c['precio_venta']) - coste
            txt = (f"💰 <b>¡Vendido!</b> {modelo} por <b>{float(c['precio_venta']):.0f} €</b> · "
                   f"beneficio <b>{'+' if ben >= 0 else ''}{ben:.0f} €</b> (costó {coste:.0f} € en total)")
        telegram.enviar(txt, tema)
        est['compras'][cid] = ahora
    ids = {c.get('id') for c in registro.get('compras', [])}
    est['compras'] = {k: v for k, v in est['compras'].items() if k in ids}

    guardar('guardados_info.json', info)
    guardar('estado_web.json', est)
    return registro, est


# ------------------------------------------------------------------ resumen diario
def resumen_diario(activos, seguidos_ventas, registro, est, temas):
    hoy = datetime.now(MADRID)
    if hoy.hour < config.RESUMEN_HORA or est.get('resumen') == hoy.strftime('%Y-%m-%d'):
        return
    e = html.escape
    inicio_dia = int(hoy.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
    vivos = [a for a in activos.values() if a.get('estado', 'activo') == 'activo'
             and a['avisado_ms'] >= ahora_ms() - config.DIAS_ACTIVO * 86400000]
    hoy_av = [a for a in vivos if a['avisado_ms'] >= inicio_dia]
    buenos = sorted([a for a in vivos if a['eval'].get('categoria') != 'trampa'], key=lambda a: -a['eval']['beneficio_oferta'])[:5]
    l = [f"🌙 <b>Resumen del día · {hoy.strftime('%d/%m')}</b>", '',
         f"Hoy: <b>{len(hoy_av)}</b> avisos nuevos ({sum(a['eval'].get('categoria') == 'chollazo' for a in hoy_av)} chollazos). "
         f"Siguen a la venta <b>{len(vivos)}</b>."]
    if buenos:
        l += ['', '<b>Los mejores que siguen activos:</b>']
        for a in buenos:
            d = a['eval']
            l.append(f"• <a href=\"{e(a['url'])}\">{e(a['modelo'])}</a> · {a['precio']:.0f} € → máx {d['max_pagar']} € · "
                     f"ganas ~{d['beneficio_oferta']} € · {e(a.get('zona') or '')}" + (f" ~{a['km']} km" if a.get('km') is not None else ''))
    compras = registro.get('compras', [])
    if compras:
        mes = hoy.strftime('%Y-%m')
        def coste(c):
            return (float(c.get('precio_compra') or 0) + sum(float(r.get('coste') or 0) for r in c.get('reparaciones') or [])
                    + float(c.get('gasolina') or 0) + float(c.get('otros') or 0))
        vend_mes = [c for c in compras if c.get('precio_venta') not in (None, '') and (c.get('fecha_venta') or '').startswith(mes)]
        stock = [c for c in compras if c.get('precio_venta') in (None, '')]
        gan = sum(float(c['precio_venta']) - coste(c) for c in vend_mes)
        l += ['', f"💰 Este mes: <b>{'+' if gan >= 0 else ''}{gan:.0f} €</b> en {len(vend_mes)} venta{"s" if len(vend_mes) != 1 else ""} · "
                  f"📦 En stock: {len(stock)} ({sum(coste(c) for c in stock):.0f} € invertidos)"]
    ventas_hoy = [v for v in seguidos_ventas if v['fin'] >= inicio_dia and v['como'] != 'no']
    rapidos = {}
    for v in seguidos_ventas:
        if v['t'] == 'listo' and v['como'] != 'no' and v['f'] == 'iphone':
            rapidos.setdefault(v['m'], []).append(v['dias'])
    top = sorted([(m, statistics.median(d), len(d)) for m, d in rapidos.items() if len(d) >= 3], key=lambda x: x[1])[:3]
    l += ['', f"📊 Hoy se han vendido o retirado <b>{len(ventas_hoy)}</b> de los anuncios que sigo."]
    if top:
        l.append('Los que antes se venden: ' + ', '.join(f"{e(m)} (~{round(d):d} días)" for m, d, n in top) + '.')
    mapa = (os.environ.get('MAPA_URL') or '').rstrip('/')
    telegram.enviar('\n'.join(l), temas.get('equipo'), [[{'text': '🗺️ Abrir el radar', 'url': mapa}]] if mapa else None)
    est['resumen'] = hoy.strftime('%Y-%m-%d')
    guardar('estado_web.json', est)


# ------------------------------------------------------------------ revisión completa
def aprender_y_estudiar(precios, seguidos, registro, condicion=None):
    aprendido = mercado.aprender(registro, lambda m, c: estimar_venta(precios, m, c))
    aprendido['condicion'] = condicion or mercado.aprender_condicion(VENTAS)

    def venta_modelo(m, cap):
        v, n = mercado.venta_real(VENTAS, m, cap)
        if v:
            return v * 0.97 * mercado.AJUSTE_VENTA, f'{n} ventas reales'
        ref = referencia(precios, m, cap)
        return (ref * config.VENTA_FACTOR * mercado.AJUSTE_VENTA, 'anuncios a la venta') if ref else (None, None)
    nuevo = mercado.estudio(seguidos, VENTAS, venta_modelo, aprendido)
    viejo = cargar('estudio.json', {})
    if {k: v for k, v in viejo.items() if k != 'actualizado_ms'} != json.loads(json.dumps(nuevo, ensure_ascii=False)):
        nuevo['actualizado_ms'] = ahora_ms()
        guardar('estudio.json', nuevo)


def revisar_bajadas(ids, precios, temas, activos, vigilar, vistos):
    """Anuncios seguidos que han bajado de precio: si ahora son chollo (o casi), se avisa."""
    n = 0
    for iid in ids[:20]:
        if iid in activos:
            continue                                   # los avisados ya se revisan aparte
        det = detalle(iid)
        if not isinstance(det, dict):
            continue
        a = preparar(item_de_detalle(det))
        if not a:
            continue
        ref = referencia(precios, a['modelo'], a['capacidad'])
        if not ref:
            continue
        poner_venta(a, precios)
        veredicto, d = evaluar(a, ref)
        regatear = veredicto == 'vigilar' and a['precio'] <= d['max_pagar'] * config.REGATEO_AVISO
        if veredicto != 'avisar' and not regatear:
            continue
        if regatear and d['categoria'] != 'trampa':
            d['categoria'] = 'regatear'
        a['eval'] = d
        if not interesa(a):
            continue
        vigilar.pop(iid, None)
        if completar(a) and avisar(a, temas, activos, cabecera='📉 <b>Ha bajado de precio</b> y ahora sale a cuenta'):
            n += 1
        vistos[iid] = ahora_ms()
        time.sleep(0.5)
    return n


def duplicado(a, activos):
    """El mismo móvil anunciado en Wallapop y en Milanuncios (mismo modelo, precio y pueblo en 3 días)."""
    corte = ahora_ms() - 3 * 86400000
    for b in activos.values():
        if (b.get('origen', 'wallapop') != a.get('origen', 'wallapop') and b['modelo'] == a['modelo']
                and abs(b['precio'] - a['precio']) <= 5 and (b.get('zona') or '').lower() == (a.get('zona') or '').lower()
                and b.get('avisado_ms', 0) >= corte):
            return True
    return False


def barrer(seguidos, precios, vistos_items, vistos, activos, vigilar):
    """Repasa a fondo un par de modelos de iPhone por pasada para seguir todos los anuncios a la venta.
    Si encuentra uno publicado en las últimas 24 h que se nos había escapado, lo devuelve para analizarlo."""
    est = cargar('barrido.json', {'i': 0})
    lista = config.BARRIDO
    nuevos, añadidos = [], 0
    for k in range(config.BARRIDO_POR_VEZ):
        for it in wallapop.buscar(lista[(est['i'] + k) % len(lista)], config.BARRIDO_PAGINAS):
            if it['id'] in vistos_items:
                continue
            vistos_items[it['id']] = True
            a = preparar(it)
            if not a:
                continue
            antes = len(seguidos)
            mercado.seguir(seguidos, a)
            añadidos += len(seguidos) - antes
            e = a['est']
            if not (e['grave'] or e['averias'] or e['extras'] or e['roto_sin_precisar']) and not a['tienda']:
                anotar_precio(precios, a['modelo'], a['id'], a['precio'], a['capacidad'])
            reciente = (a.get('publicado_ms') or 0) >= ahora_ms() - 86400000
            if reciente and a['id'] not in vistos and a['id'] not in activos and a['id'] not in vigilar:
                nuevos.append(a)
    est['i'] = (est['i'] + config.BARRIDO_POR_VEZ) % len(lista)
    guardar('barrido.json', est)
    return nuevos, añadidos


def exportar_analizador(precios):
    """analizador.json: reglas y precios para que la web analice un anuncio al momento, sin esperar al bot."""
    tabla = {}
    for nombre, lista in precios.items():
        caps = sorted({x[3] for x in lista if x[3]}, key=lambda c: (len(c), c))
        d = {}
        for cap in [None] + caps:
            r = mercado.rango(VENTAS, nombre, cap)
            ref = referencia(precios, nombre, cap)
            if r and (cap is None or r['cap'] == cap):
                e = {'baja': r['baja'], 'media': r['media'], 'alta': r['alta'], 'n': r['n'], 'fiab': r['fiab'], 'k': 0.97,
                     'fuente': f"{r['n']} ventas reales"}
            else:
                q = pedidos(precios, nombre, cap)
                if not q or (cap and len([x for x in lista if x[3] == cap]) < 6):
                    continue
                e = {'baja': q[0], 'media': q[1], 'alta': q[2], 'n': q[3], 'fiab': 'baja', 'k': config.VENTA_FACTOR,
                     'fuente': f'{q[3]} anuncios a la venta, aún sin ventas reales'}
            e = {k: (round(v, 1) if isinstance(v, float) else v) for k, v in e.items()}
            e['ref'] = round(ref, 1) if ref else None
            d[cap or '*'] = e
        if d:
            dv, nd = mercado.dias_venta(VENTAS, nombre)
            tabla[nombre] = {'caps': d, 'dias': dv, 'dias_n': nd}
    piezas = {f'iPhone {k}': v for k, v in config.IPHONE_PIEZAS.items()}
    R = analisis
    datos = {
        'precios': tabla, 'piezas': piezas, 'piezas_defecto': config.IPHONE_POR_DEFECTO, 'extras': config.EXTRAS,
        'factores': mercado.F, 'ajuste': getattr(config, 'AJUSTE_VENTA', 1.0),
        'beneficio_min': {f'{k[0]}_{k[1]}': v for k, v in config.BENEFICIO_MIN.items()},
        'coste_fijo': config.COSTE_FIJO, 'precio_max': config.PRECIO_MAX,
        'reglas': {
            'grave': {k: rx.pattern for k, rx in R._GRAVE.items()}, 'grave_literal': R._GRAVE_LITERAL.pattern,
            'sospecha': R._SOSPECHA.pattern, 'averias': {k: rx.pattern for k, rx in R._AVERIAS.items()},
            'extras': {k: rx.pattern for k, rx in R._EXTRAS.items()}, 'roto': R._ROTO_GENERICO.pattern,
            'marcas': R._MARCAS.pattern, 'neg': R._NEG.pattern,
        },
    }
    viejo = cargar('analizador.json', {})
    if {k: v for k, v in viejo.items() if k != 'actualizado_ms'} != json.loads(json.dumps(datos, ensure_ascii=False)):
        datos['actualizado_ms'] = ahora_ms()
        guardar('analizador.json', datos)


def ejecutar():
    global VENTAS
    precios = cargar('precios.json', {})
    vistos = cargar('vistos.json', {})
    activos = cargar('activos.json', {})
    vigilar = cargar('vigilar.json', {})
    seguidos = cargar('mercado.json', {})
    VENTAS = cargar('ventas.json', [])
    condicion = mercado.aprender_condicion(VENTAS)
    DESCARTADOS.update(cargar('descartados.json', {}).get('items', {}))
    temas = telegram.preparar_temas(cargar('temas.json', {}))
    mercado.aprender(cargar('registro.json', {}), lambda m, c: estimar_venta(precios, m, c))

    vistos_items, nuevos = {}, []
    for palabras, paginas in config.BUSQUEDAS:
        for it in wallapop.buscar(palabras, paginas):
            if it['id'] in vistos_items:
                continue
            a = preparar(it)
            vistos_items[it['id']] = True
            if not a:
                continue
            mercado.seguir(seguidos, a)
            est = a['est']
            limpio = not (est['grave'] or est['averias'] or est['extras'] or est['roto_sin_precisar'])
            if limpio and not a['tienda']:
                anotar_precio(precios, a['modelo'], a['id'], a['precio'], a['capacidad'])
            if a['id'] in vistos or a['id'] in activos or a['id'] in vigilar:
                continue
            nuevos.append(a)

    de_milanuncios = 0
    for texto, cuantos, cat in getattr(config, 'MILANUNCIOS', []):
        for it in milanuncios.buscar(texto, cuantos, cat):
            if it['id'] in vistos_items:
                continue
            vistos_items[it['id']] = True
            a = preparar(it)
            if not a or a.get('km') is None or a['km'] > config.RADIO_KM:
                continue
            de_milanuncios += 1
            mercado.seguir(seguidos, a)
            est = a['est']
            if not (est['grave'] or est['averias'] or est['extras'] or est['roto_sin_precisar']) and not a['tienda']:
                anotar_precio(precios, a['modelo'], a['id'], a['precio'], a['capacidad'])
            if a['id'] in vistos or a['id'] in activos or a['id'] in vigilar:
                continue
            nuevos.append(a)

    escapados, barridos = barrer(seguidos, precios, vistos_items, vistos, activos, vigilar)
    nuevos += escapados

    avisados = 0
    candidatos = []
    for a in nuevos:
        ref = referencia(precios, a['modelo'], a['capacidad'])
        poner_venta(a, precios)
        veredicto, d = evaluar(a, ref)
        if veredicto == 'vigilar' and a['precio'] <= d['max_pagar'] * config.REGATEO_AVISO:
            if d['categoria'] != 'trampa':
                d['categoria'] = 'regatear'
            a['eval'] = d
            if interesa(a):
                candidatos.append(a)
        elif veredicto == 'vigilar':
            a['eval'], a['ref'], a['avisado_ms_vigilar'] = d, ref, ahora_ms()
            vigilar[a['id']] = {k: v for k, v in a.items()}
        elif veredicto == 'avisar':
            a['eval'] = d
            if interesa(a):
                candidatos.append(a)
        if ref:                      # sin precio de referencia aún: se mirará otra vez cuando lo haya
            vistos[a['id']] = ahora_ms()

    candidatos.sort(key=lambda a: (a['eval']['categoria'] == 'regatear', -a['eval']['beneficio_oferta']))
    for a in candidatos:
        if duplicado(a, activos):
            vistos[a['id']] = ahora_ms()
            continue
        if completar(a) and avisar(a, temas, activos):
            avisados += 1
        time.sleep(1)

    bajadas = revisar_conocidos(activos, vigilar, temas, precios)
    registro, est = procesar_web(temas, activos, precios, revisar_estado=True)
    mercado.BAJADAS.clear()
    cerrados = mercado.revisar(seguidos, VENTAS)
    avisados += revisar_bajadas(mercado.BAJADAS, precios, temas, activos, vigilar, vistos)

    corte = ahora_ms() - 20 * 86400000
    vistos = {k: v for k, v in vistos.items() if v >= corte}
    activos = {k: v for k, v in activos.items() if v['avisado_ms'] >= corte}
    for nombre, datos in (('precios.json', precios), ('vistos.json', vistos), ('activos.json', activos),
                          ('vigilar.json', vigilar), ('temas.json', temas), ('mercado.json', seguidos), ('ventas.json', VENTAS)):
        guardar(nombre, datos)
    exportar(activos, vigilar)
    # lo que viene ahora es extra: si algo falla, se avisa en el registro pero la pasada no se pierde
    for nombre, paso in (('estudio', lambda: aprender_y_estudiar(precios, seguidos, registro, condicion)),
                         ('analizador', lambda: exportar_analizador(precios)),
                         ('resumen diario', lambda: resumen_diario(activos, VENTAS, registro, est, temas))):
        try:
            paso()
        except Exception as ex:
            import traceback
            traceback.print_exc()
            print(f'aviso: falló el paso «{nombre}»: {ex}', file=sys.stderr)
    print(f'{len(vistos_items)} anuncios revisados ({de_milanuncios} de Milanuncios en el radio) · {len(nuevos)} nuevos de modelos que tratamos · '
          f'{avisados} avisos · {bajadas} bajadas de precio · {len(vigilar)} vigilados · '
          f'mercado: {len(seguidos)} seguidos (+{barridos} del barrido), {cerrados} vendidos/retirados en esta pasada, {len(VENTAS)} ventas en memoria · '
          f'{sum(len(v) for v in precios.values())} precios de referencia en {len(precios)} modelos')


def solo_web():
    """Lo que se ejecuta nada más guardar algo desde la web: avisar en Telegram y analizar enlaces."""
    global VENTAS
    precios = cargar('precios.json', {})
    VENTAS = cargar('ventas.json', [])
    mercado.aprender_condicion(VENTAS)
    temas = telegram.preparar_temas(cargar('temas.json', {}))
    mercado.aprender(cargar('registro.json', {}), lambda m, c: estimar_venta(precios, m, c))
    procesar_web(temas, cargar('activos.json', {}), precios)
    guardar('temas.json', temas)


if __name__ == '__main__':
    solo_web() if '--web' in sys.argv else ejecutar()
