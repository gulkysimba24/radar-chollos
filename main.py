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

import analisis, config, mercado, telegram, wallapop

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


VENTAS = []          # ventas vistas por la memoria del mercado (se cargan en ejecutar)


def poner_venta(a):
    """Si hay bastantes ventas reales de este modelo, el bot usa ese precio en vez del de los anuncios."""
    v, n = mercado.venta_real(VENTAS, a['modelo'], a.get('capacidad'))
    a['venta_real'] = v * 0.97 if v else None          # un poco menos: el último precio suele regatearse
    a['fuente_venta'] = f'{n} ventas reales' if v else None
    d, nd = mercado.dias_venta(VENTAS, a['modelo'])
    a['dias_venta'] = d
    a['dias_venta_n'] = nd


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
    return analisis.mediana([x[1] for x in lista], 6)


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
    ya = '⚡ Ya está por debajo del máximo' if a['precio'] <= d['max_pagar'] else '🤝 Hay que regatear para que salga'
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
           'trampa': f"🟣 <b>¿TRAMPA?</b> {e(d.get('motivo_trampa') or '')}. Puede ser estafa o tener algo oculto, aunque a veces es un chollo real."
           }.get(d.get('categoria'), '🔵 Chollo normal')
    if d.get('categoria') == 'trampa':
        riesgo = 'Pide factura y foto del IMEI en Ajustes antes de quedar. Nunca pagues ni envíes nada por adelantado.'
    lineas += [cat, titulo, tipo] + ([riesgo] if riesgo else []) + [
        '',
        f"💶 Piden <b>{a['precio']:.0f} €</b> → ofrece <b>{d['oferta']} €</b> · máximo <b>{d['max_pagar']} €</b>",
        f"📈 Se vende por ~{d['venta']} €{' (según ' + d['fuente_venta'] + ')' if d.get('fuente_venta') else ''} · ganas <b>{'+' if d['beneficio_oferta'] > 0 else ''}{d['beneficio_oferta']} €</b> con tu oferta"
        f" ({'+' if ben > 0 else ''}{ben} € pagando lo que piden)",
        ya,
    ] + ([f"⏱️ Este modelo se suele vender en <b>~{a['dias_venta']:g} días</b> ({a['dias_venta_n']} ventas vistas)"]
         if a.get('dias_venta') is not None else []) + [
        f"📍 {e(a.get('zona') or 'Madrid')} · <b>~{a['km']} km</b> de {config.ORIGEN_NOMBRE}" if a.get('km') is not None
        else f"📍 {e(a.get('zona') or 'Madrid')}",
        f"🔎 {e(a['resumen'])}",
    ]
    cont = a.get('contadores') or {}
    actividad = f"🕒 Publicado {hace(a.get('publicado_ms'))}"
    if cont:
        actividad += f" · 👀 {cont.get('views', 0)} visitas · ❤️ {cont.get('favorites', 0)} · 💬 {cont.get('conversations', 0)} chats"
    lineas += [actividad, '', '<b>Pregunta antes de ir:</b>']
    lineas += [f'• {e(p)}' for p in a['preguntas']]
    lineas += ['', f"<b>Regateo:</b> {e(a['regateo'])}", '', '<b>Mensaje para copiar:</b>', f"<code>{e(a['mensaje'])}</code>"]
    return '\n'.join(lineas)


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
        'url': f"https://es.wallapop.com/item/{item.get('web_slug')}", 'publicado_ms': item.get('created_at'),
        'tienda': wallapop.flag(item.get('is_top_profile')),
        'est': analisis.estado(titulo, desc),
        'foto': (((item.get('images') or [{}])[0].get('urls') or {}).get('medium')),
    }


def completar(a):
    """Añade datos de la ficha completa: estado según Wallapop, capacidad, visitas."""
    det = wallapop.detalle(a['id'])
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
        'precio_inicial': a.get('precio_inicial', a['precio']),
    }


def avisar(a, temas, activos, cabecera=None):
    a['resumen'], a['preguntas'], a['regateo'], a['mensaje'] = analisis.textos(a)
    a['avisado_ms'] = ahora_ms()
    msg = telegram.enviar(texto_aviso(a, cabecera), temas.get(tema_de(a)), botones(a), silencioso=silencio(), foto=a.get('foto'))
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
                        key=lambda a: a.get('revisado_ms', 0))[:40]
    for a in pendientes:
        det = wallapop.detalle(a['id'])
        a['revisado_ms'] = ahora_ms()
        if det == 'error':
            continue
        if det is None:
            a['estado'] = 'vendido'
            telegram.editar(a.get('msg_id'), '❌ <b>Ya no está a la venta</b> (vendido o retirado)\n\n' + texto_aviso(a), foto=a.get('foto'))
            continue
        nuevo = float(((det.get('price') or {}).get('cash') or {}).get('amount') or a['precio'])
        if nuevo < a['precio'] - 0.5:
            antes = a['precio']
            a.setdefault('precio_inicial', antes)
            a['precio'] = nuevo
            ref = referencia(precios, a['modelo'], a.get('capacidad'))
            poner_venta(a)
            v, d = analisis.evaluar(a, ref or a['eval']['ref_mercado'])
            if d:
                a['eval'] = d
            a['resumen'], a['preguntas'], a['regateo'], a['mensaje'] = analisis.textos(a)
            telegram.editar(a.get('msg_id'), f'📉 <b>Ha bajado de {antes:.0f} € a {nuevo:.0f} €</b>\n\n' + texto_aviso(a), botones(a), foto=a.get('foto'))
            telegram.responder(a.get('msg_id'), f'📉 {html.escape(a["modelo"])} ha bajado a <b>{nuevo:.0f} €</b>', temas.get(tema_de(a)))
            avisos += 1
        time.sleep(0.4)

    for vid, a in sorted(vigilar.items(), key=lambda kv: kv[1].get('revisado_ms', 0))[:30]:
        det = wallapop.detalle(vid)
        a['revisado_ms'] = ahora_ms()
        if det is None or a['avisado_ms_vigilar'] < ahora_ms() - 10 * 86400000:
            vigilar.pop(vid, None)
            continue
        if det == 'error':
            continue
        nuevo = float(((det.get('price') or {}).get('cash') or {}).get('amount') or a['precio'])
        if nuevo < a['precio'] - 0.5:
            antes = a['precio']
            a['precio'] = nuevo
            ref = referencia(precios, a['modelo'], a.get('capacidad')) or a.get('ref')
            poner_venta(a)
            veredicto, d = analisis.evaluar(a, ref)
            if veredicto == 'avisar':
                a['eval'] = d
                a['precio_inicial'] = antes
                if completar(a) and avisar(a, temas, activos, cabecera=f'📉 <b>Ha bajado de {antes:.0f} € a {nuevo:.0f} €</b>'):
                    avisos += 1
                vigilar.pop(vid, None)
        time.sleep(0.4)
    return avisos


def exportar(activos):
    limite = ahora_ms() - config.DIAS_ACTIVO * 86400000
    lista = []
    for a in activos.values():
        if a['avisado_ms'] < limite:
            continue
        if a.get('estado') == 'vendido' and a.get('revisado_ms', 0) < ahora_ms() - 86400000:
            continue
        lista.append(ficha_web(a, a.get('estado', 'activo')))
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
    }


def id_de_enlace(url):
    """Saca el id interno de Wallapop de un enlace tipo https://es.wallapop.com/item/iphone-13-...-1234567890."""
    m = re.search(r'/item/([a-z0-9-]+)', url or '')
    if not m:
        return None
    slug = m.group(1)
    code, body = wallapop._get(f'https://es.wallapop.com/item/{slug}')
    if code == 200:
        m2 = re.search(r'"id":"([a-z0-9]{10,14})"', body)
        if m2:
            return m2.group(1)
    palabras = ' '.join(w for w in slug.split('-')[:-1] if w)[:60]       # plan B: buscarlo por el título
    for it in wallapop.buscar(palabras, 2, radio_km=200):
        if it.get('web_slug') == slug:
            return it['id']
    return None


def valorar(a, precios):
    """Análisis de un anuncio que habéis guardado vosotros, aunque el bot no lo vea chollo."""
    ref = referencia(precios, a['modelo'], a.get('capacidad'))
    poner_venta(a)
    if not ref and not a.get('venta_real'):
        return None
    v, d = analisis.evaluar(a, ref or a['venta_real'] / config.VENTA_FACTOR)
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
    return {'riesgo': 'bajo', 'pct_mercado': round(a['precio'] / ref * 100) if ref else None, 'categoria': 'normal',
            'motivo_trampa': None, 'fuente_venta': a.get('fuente_venta'), 'tipo': tipo, 'nivel': nivel, 'reparacion': detalle,
            'coste_reparacion': round(coste), 'ref_mercado': round(ref or 0), 'venta': round(venta),
            'max_pagar': round(maxp), 'oferta': oferta,
            'beneficio_precio_pedido': round(venta - a['precio'] - coste - fijo),
            'beneficio_oferta': round(venta - oferta - coste - fijo)}


def analizar_guardado(wid, precios):
    det = wallapop.detalle(wid)
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
            lineas.append('No he podido abrir el enlace para analizarlo, pero queda guardado.')
        url = f.get('url') or i.get('url') or g.get('url')
        bot = [[{'text': '📲 Abrir anuncio', 'url': url}]] if url else []
        if mapa:
            bot.append([{'text': '⭐ Ver guardados', 'url': f'{mapa}/#guardados'}])
        telegram.enviar('\n'.join(lineas), tema, bot or None, foto=f.get('foto') or i.get('foto'))
        est['guardados'].append(gid)

    for gid in list(info):
        if gid not in guardados:
            info.pop(gid)
    est['guardados'] = [g for g in est['guardados'] if g in guardados]

    if revisar_estado:            # ¿alguno guardado se ha vendido o ha bajado?
        pend = sorted([(gid, i) for gid, i in info.items() if i.get('wid') and i.get('estado') == 'activo'],
                      key=lambda kv: kv[1].get('revisado_ms', 0))[:25]
        for gid, i in pend:
            det = wallapop.detalle(i['wid'])
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
def aprender_y_estudiar(precios, seguidos, registro):
    aprendido = mercado.aprender(registro, lambda m, c: estimar_venta(precios, m, c))

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


def ejecutar():
    global VENTAS
    precios = cargar('precios.json', {})
    vistos = cargar('vistos.json', {})
    activos = cargar('activos.json', {})
    vigilar = cargar('vigilar.json', {})
    seguidos = cargar('mercado.json', {})
    VENTAS = cargar('ventas.json', [])
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
            if a['id'] in vistos or a['id'] in activos or a['id'] in vigilar or a['tienda']:
                continue
            nuevos.append(a)

    avisados = 0
    candidatos = []
    for a in nuevos:
        ref = referencia(precios, a['modelo'], a['capacidad'])
        poner_venta(a)
        veredicto, d = analisis.evaluar(a, ref)
        if veredicto == 'vigilar':
            a['eval'], a['ref'], a['avisado_ms_vigilar'] = d, ref, ahora_ms()
            vigilar[a['id']] = {k: v for k, v in a.items()}
        elif veredicto == 'avisar':
            a['eval'] = d
            candidatos.append(a)
        if ref:                      # sin precio de referencia aún: se mirará otra vez cuando lo haya
            vistos[a['id']] = ahora_ms()

    candidatos.sort(key=lambda a: -a['eval']['beneficio_oferta'])
    for a in candidatos:
        if completar(a) and avisar(a, temas, activos):
            avisados += 1
        time.sleep(1)

    bajadas = revisar_conocidos(activos, vigilar, temas, precios)
    registro, est = procesar_web(temas, activos, precios, revisar_estado=True)
    cerrados = mercado.revisar(seguidos, VENTAS)

    corte = ahora_ms() - 20 * 86400000
    vistos = {k: v for k, v in vistos.items() if v >= corte}
    activos = {k: v for k, v in activos.items() if v['avisado_ms'] >= corte}
    for nombre, datos in (('precios.json', precios), ('vistos.json', vistos), ('activos.json', activos),
                          ('vigilar.json', vigilar), ('temas.json', temas), ('mercado.json', seguidos), ('ventas.json', VENTAS)):
        guardar(nombre, datos)
    exportar(activos)
    aprender_y_estudiar(precios, seguidos, registro)
    resumen_diario(activos, VENTAS, registro, est, temas)
    print(f'{len(vistos_items)} anuncios revisados · {len(nuevos)} nuevos de modelos que tratamos · '
          f'{avisados} avisos · {bajadas} bajadas de precio · {len(vigilar)} vigilados · '
          f'mercado: {len(seguidos)} seguidos, {cerrados} vendidos/retirados en esta pasada, {len(VENTAS)} ventas en memoria · '
          f'{sum(len(v) for v in precios.values())} precios de referencia en {len(precios)} modelos')


def solo_web():
    """Lo que se ejecuta nada más guardar algo desde la web: avisar en Telegram y analizar enlaces."""
    global VENTAS
    precios = cargar('precios.json', {})
    VENTAS = cargar('ventas.json', [])
    temas = telegram.preparar_temas(cargar('temas.json', {}))
    mercado.aprender(cargar('registro.json', {}), lambda m, c: estimar_venta(precios, m, c))
    procesar_web(temas, cargar('activos.json', {}), precios)
    guardar('temas.json', temas)


if __name__ == '__main__':
    solo_web() if '--web' in sys.argv else ejecutar()
