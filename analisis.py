"""Detecta modelo, estado y avería de un anuncio y calcula si es un chollo."""
import math
import re
import statistics

import config

# ---------------------------------------------------------------- modelos
_IPH = re.compile(r'iphone\s*(se|xs\s*max|xr|xs|x|1[0-7]e?|[89])\b\s*(pro\s*max|pro|plus|mini|max)?', re.I)
_SAM_S = re.compile(r'\bs\s?(2[0-6])\s*(ultra|plus|\+|fe)?(?![0-9])', re.I)
_SAM_A = re.compile(r'\ba\s?([1-9][0-9])\b', re.I)
_PIXEL = re.compile(r'pixel\s*(\d{1,2})\s*(pro\s*xl|pro\s*fold|pro|a|xl|fold)?\b', re.I)
_REDMI = re.compile(r'redmi\s*note\s*(\d{2})\s*(pro\s*\+|pro\s*plus|pro|s)?', re.I)
_POCO = re.compile(r'poco\s*([xfm]\d)\s*(pro|gt|ultra)?', re.I)
_XIAOMI = re.compile(r'xiaomi\s*(1[0-5])\s*(t\s*pro|t|ultra|pro|lite)?\b', re.I)


def modelo(titulo):
    """('iphone'|'android', nombre normalizado, gama android) o None si no es un móvil que tratemos."""
    t = titulo.lower()
    m = _IPH.search(t)
    if m:
        num, suf = m.group(1).replace(' ', ''), (m.group(2) or '').strip()
        if num in ('8', '9'):
            return None                      # demasiado viejo para revender bien
        num = {'se': 'SE', 'x': 'X', 'xr': 'XR', 'xs': 'XS', 'xsmax': 'XS Max'}.get(num, num)
        suf = re.sub(r'\s+', ' ', suf)
        suf = {'pro max': 'Pro Max', 'pro': 'Pro', 'plus': 'Plus', 'mini': 'mini', 'max': 'Pro Max' if num != 'XS' else 'Max'}.get(suf, '')
        if num == 'XS' and suf == 'Max':
            num, suf = 'XS Max', ''
        return 'iphone', ('iPhone ' + num + (' ' + suf if suf else '')).strip(), None
    if re.search(r'fold|flip', t):
        return None                          # plegables: reparación cara y arriesgada
    if 'samsung' in t or 'galaxy' in t:
        m = _SAM_S.search(t)
        if m:
            suf = (m.group(2) or '').lower()
            suf = {'ultra': ' Ultra', 'plus': '+', '+': '+', 'fe': ' FE'}.get(suf, '')
            gama = 'samsung_s_ultra' if 'Ultra' in suf else ('samsung_s_fe' if 'FE' in suf else 'samsung_s')
            return 'android', f'Galaxy S{m.group(1)}{suf}', gama
        m = _SAM_A.search(t)
        if m and int(m.group(1)) >= 34:
            return 'android', f'Galaxy A{m.group(1)}', 'samsung_a'
        return None
    m = _PIXEL.search(t)
    if m and int(m.group(1)) >= 6:
        suf = re.sub(r'\s+', ' ', (m.group(2) or '').lower())
        if 'fold' in suf:
            return None
        nombre = {'pro xl': ' Pro XL', 'pro': ' Pro', 'a': 'a', 'xl': ' XL'}.get(suf, '')
        return 'android', f'Pixel {m.group(1)}{nombre}', 'pixel_pro' if 'Pro' in nombre else 'pixel'
    m = _REDMI.search(t)
    if m and int(m.group(1)) >= 12:
        suf = re.sub(r'\s+', '', (m.group(2) or '').lower())
        suf = {'pro+': ' Pro+', 'proplus': ' Pro+', 'pro': ' Pro', 's': 'S'}.get(suf, '')
        return 'android', f'Redmi Note {m.group(1)}{suf}', 'xiaomi'
    m = _POCO.search(t)
    if m:
        return 'android', f'POCO {m.group(1).upper()}' + (' ' + m.group(2).upper() if m.group(2) else ''), 'xiaomi'
    m = _XIAOMI.search(t)
    if m and int(m.group(1)) >= 12:
        suf = re.sub(r'\s+', ' ', (m.group(2) or '').lower())
        suf = {'t pro': 'T Pro', 't': 'T', 'ultra': ' Ultra', 'pro': ' Pro', 'lite': ' Lite'}.get(suf, '')
        return 'android', f'Xiaomi {m.group(1)}{suf}', 'xiaomi'
    return None


def capacidad(texto):
    m = re.search(r'\b(64|128|256|512)\s?gb|\b(1)\s?tb', texto, re.I)
    if not m:
        return ''
    return f'{m.group(1)} GB' if m.group(1) else '1 TB'


def bateria(texto):
    m = re.search(r'(?:bater[ií]a|salud|capacidad|condici[oó]n)[^0-9%]{0,25}(\d{2,3}) ?%|(\d{2,3}) ?% ?(?:de )?(?:bater[ií]a|salud|capacidad)', texto, re.I)
    if not m:
        return None
    v = int(m.group(1) or m.group(2))
    return v if 50 <= v <= 100 else None


# ---------------------------------------------------------------- estado / avería
_ACCESORIO = re.compile(r'^(funda|carcasa|protector|cristal templado|cargador|cable|pantalla|repuesto|bater[ií]a|tapa|c[aá]mara|lote|caja)\b|'
                        r'\b(busco|compro|cambio por|solo cambio|reparaci[oó]n de|reparamos|servicio t[eé]cnico|cambio de pantalla)\b', re.I)
_NEG = re.compile(r'(sin|no|ni|ningun[ao]?|nunca|cero|nada de)\s+(\S+\s+){0,3}$', re.I)
_GRAVE = {
    'bloqueado o con cuenta': r'bloquead|cuenta (de )?(google|apple|samsung|mi) (vinculada|activa|puesta)|blacklist|lista negra|reportad|icloud (activ|puest|bloque|vinculad)',
    'no enciende o placa': r'no enciende|no arranca|placa base|se reinicia|bucle|logo de apple|muerto',
    'Face ID o huella rotos': r'face ?id (no|roto|falla|desactivad)|no (funciona|va) (el )?face ?id|huella no|sin face ?id',
    'mojado': r'mojad|se (me )?cay[oó] al agua|humedad|oxidad',
    'para piezas': r'para piezas|despiece|solo piezas|para repuestos|destinado a piezas|no funciona nada',
    'pantalla sin imagen': r'no da imagen|sin imagen|pantalla (en )?negra|t[aá]ctil no (funciona|va)|no funciona el t[aá]ctil|pantalla no funciona|manchas? (verde|negra|morada)|l[ií]neas? (verdes?|verticales?|horizontales?)',
    'tienda o reacondicionado': r'reacondicionad|garant[ií]a de \d|somos (una )?tienda|tienda f[ií]sica|factura con iva',
    'estafa probable': r'solo env[ií]o|s[oó]lo env[ií]o|pago (por )?adelantado|bizum antes|transferencia antes|western|paypal amigos',
}
_GRAVE = {k: re.compile(v, re.I) for k, v in _GRAVE.items()}
_AVERIAS = {
    'pantalla': r'pantalla.{0,25}(rot|rajad|agriet|partid|grieta|estrellad|astillad)|cristal (frontal )?(rot|rajad)|(rota|rajada|agrietada) la pantalla|grietas? en la pantalla|pantalla da[ñn]ada',
    'trasera': r'trasera.{0,12}(rot|rajad|agriet)|tapa.{0,15}(rot|rajad)|parte (de )?(atr[aá]s|trasera).{0,10}rot|cristal trasero.{0,10}rot|detr[aá]s.{0,15}rot',
    'batería': r'(salud|bater[ií]a|capacidad)[^0-9%]{0,20}(6\d|7\d) ?%|(6\d|7\d) ?% ?(de )?(salud|bater)|cambiar (la )?bater|bater[ií]a.{0,20}(mantenimiento|servicio|desconocida|no original|dura poco|se descarga)',
}
_AVERIAS = {k: re.compile(v, re.I) for k, v in _AVERIAS.items()}
_EXTRAS = {
    'cámara': r'c[aá]mara.{0,30}(rota|no funciona|falla|no enfoca|borros|vibra|mancha)|menos (la )?c[aá]mara|lente.{0,10}rot|teleobjetivo|gran angular no',
    'puerto de carga': r'no carga|carga mal|puerto de carga|conector de carga|carga solo (inal|por im)',
    'altavoz': r'altavoz.{0,20}(no|mal|roto|bajo)|suena (poco|bajo|mal)|no se oye',
    'botón': r'bot[oó]n.{0,20}(no|roto|hundido)',
}
_EXTRAS = {k: re.compile(v, re.I) for k, v in _EXTRAS.items()}
_ROTO_GENERICO = re.compile(r'\brot[oa]s?\b|grieta|rajad|golpe fuerte', re.I)
_MARCAS = re.compile(r'rayas?|rayad|rasgu[ñn]|golpes?|marcas de uso|desconchad|ara[ñn]az|rozad|desgast|piquete', re.I)


def _hay(rx, texto):
    for m in rx.finditer(texto):
        if not _NEG.search(texto[max(0, m.start() - 30):m.start()]):
            return True
    return False


def es_accesorio(titulo):
    return bool(_ACCESORIO.search(titulo.strip()))


_GRAVE_LITERAL = re.compile(r'no (est[aá] |es )?libre de (icloud|cuenta)|no (tiene|est[aá]) (el )?icloud (quitado|desvinculado)|'
                           r'con (el |su )?icloud|tiene (el )?icloud|bloqueado por icloud|sin desbloquear|'
                           r'no s[eé] (la|el) (contrase[ñn]a|c[oó]digo|apple ?id)|no recuerdo (la|el) (contrase[ñn]a|c[oó]digo|apple ?id)', re.I)


def estado(titulo, descripcion):
    """{'grave': motivo|None, 'averias': [...], 'extras': [...], 'marcas': bool, 'roto_sin_precisar': bool}"""
    texto = f'{titulo}. {descripcion}'
    grave = 'bloqueado o con cuenta' if _GRAVE_LITERAL.search(texto) else None
    grave = grave or next((k for k, rx in _GRAVE.items() if _hay(rx, texto)), None)
    averias = [k for k, rx in _AVERIAS.items() if _hay(rx, texto)]
    extras = [k for k, rx in _EXTRAS.items() if _hay(rx, texto)]
    roto = not averias and not extras and _hay(_ROTO_GENERICO, texto)
    return {'grave': grave, 'averias': averias, 'extras': extras,
            'marcas': _hay(_MARCAS, texto), 'roto_sin_precisar': roto}


# ---------------------------------------------------------------- precios de mercado
def mediana(precios, minimo=6):
    if len(precios) < minimo:
        return None
    return statistics.median(precios)


def km(lat, lng):
    if lat is None or lng is None:
        return None
    la1, lo1 = map(math.radians, config.ORIGEN)
    la2, lo2 = math.radians(lat), math.radians(lng)
    a = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return round(2 * 6371 * math.asin(math.sqrt(a)))


def costes(familia, nombre, gama, est):
    """Coste de reparación (pieza+material) y nivel: 'leve' o 'media'. None si no se arregla barato."""
    if familia == 'iphone':
        clave = nombre.replace('iPhone ', '')
        pantalla, bat, trasera, tipo_tras = config.IPHONE_PIEZAS.get(clave, config.IPHONE_POR_DEFECTO)
    else:
        pantalla, bat, trasera = config.ANDROID_PIEZAS.get(gama, (90, 20, 15))
        tipo_tras = 'tapa'
    total, nivel, detalle = 0, 'leve', []
    for a in est['averias']:
        if a == 'pantalla':
            total += pantalla; nivel = 'media'; detalle.append(f'pantalla ~{pantalla} €')
        elif a == 'batería':
            total += bat; detalle.append(f'batería ~{bat} €')
        elif a == 'trasera':
            total += trasera
            if tipo_tras == 'laser':
                nivel = 'media'; detalle.append(f'trasera en taller con láser ~{trasera} €')
            else:
                detalle.append(f'{"carcasa" if tipo_tras == "carcasa" else "tapa trasera"} ~{trasera} €')
    for e in est['extras']:
        c = config.EXTRAS[e]
        total += c
        if e == 'cámara':
            nivel = 'media'
        detalle.append(f'{e} ~{c} €')
    if len(est['averias']) + len(est['extras']) >= 3:
        return None                           # demasiadas cosas: reparación grave
    return total, nivel, detalle


def evaluar(anuncio, ref):
    """Decide si un anuncio es chollo. ref = mediana de anuncios del mismo modelo funcionando.

    Devuelve (veredicto, datos): veredicto 'avisar', 'vigilar' o None.
    """
    fam, nombre, gama = anuncio['familia'], anuncio['modelo'], anuncio['gama']
    est = anuncio['est']
    precio = anuncio['precio']
    if est['grave'] or est['roto_sin_precisar'] or not ref:
        return None, None
    if precio > config.PRECIO_MAX or precio > ref * 1.05:
        return None, None
    reparar = bool(est['averias'] or est['extras'])
    tipo = 'reparar' if reparar else 'listo'
    if reparar:
        c = costes(fam, nombre, gama, est)
        if not c:
            return None, None
        coste, nivel, detalle = c
        if precio < ref * 0.12:
            return None, None
    else:
        coste, nivel, detalle = 0, None, []
        if precio < ref * 0.45:               # demasiado barato para estar bien: suele ser trampa
            return None, None
    venta = ref * config.VENTA_FACTOR
    fijo = config.COSTE_FIJO[tipo]
    objetivo = config.BENEFICIO_MIN[(fam, tipo)]
    maxp = venta - coste - fijo - objetivo
    if maxp <= 0:
        return None, None
    ratio = precio / maxp
    if ratio <= 1 / config.MARGEN_REGATEO:
        veredicto = 'avisar'
    elif ratio <= 1 / config.MARGEN_VIGILAR:
        veredicto = 'vigilar'
    else:
        return None, None
    oferta = min(_r5(precio * (0.80 if reparar else 0.88)), _r5(maxp))
    ratio_mercado = precio / ref
    if not reparar and ratio_mercado < 0.70:
        riesgo = 'alto'
    elif (not reparar and ratio_mercado < 0.80) or (reparar and ratio_mercado < 0.30):
        riesgo = 'medio'
    else:
        riesgo = 'bajo'
    return veredicto, {
        'riesgo': riesgo, 'pct_mercado': round(ratio_mercado * 100),
        'tipo': tipo, 'nivel': nivel, 'reparacion': detalle, 'coste_reparacion': round(coste),
        'ref_mercado': round(ref), 'venta': round(venta), 'max_pagar': _r5(maxp) if maxp >= 10 else round(maxp),
        'oferta': oferta,
        'beneficio_precio_pedido': round(venta - precio - coste - fijo),
        'beneficio_oferta': round(venta - oferta - coste - fijo),
    }


def _r5(x):
    return int(round(x / 5.0) * 5)


# ---------------------------------------------------------------- textos
def textos(a):
    """Resumen de estado, preguntas, regateo y mensaje para copiar."""
    iphone = a['familia'] == 'iphone'
    est, d = a['est'], a['eval']
    partes = []
    if d['tipo'] == 'listo':
        partes.append('Sin daños según el anuncio' + (', con marcas de uso' if est['marcas'] else ''))
    else:
        nombres = {'pantalla': 'pantalla rota', 'trasera': 'trasera rota', 'batería': 'batería gastada'}
        partes.append(', '.join([nombres[x] for x in est['averias']] + [f'falla {x}' for x in est['extras']]).capitalize())
    if a.get('bateria'):
        partes.append(f"Batería {a['bateria']} %")
    if a.get('condicion'):
        partes.append(f"Wallapop dice: {a['condicion']}")
    if re.search(r'\bcaja\b', a['descripcion'], re.I):
        partes.append('Con caja')
    if re.search(r'factura', a['descripcion'], re.I):
        partes.append('Con factura')
    resumen = ' · '.join(partes)

    preg = []
    if d.get('riesgo') in ('alto', 'medio'):
        preg.append('¿Por qué lo vendes tan barato? ¿Tienes la factura de compra a tu nombre?')
        preg.append('¿Está pagado del todo (sin financiación pendiente) y comprado en España?')
    if 'pantalla' in est['averias']:
        preg.append('¿El táctil responde en toda la pantalla, también encima de las grietas? ¿Se ven manchas o líneas?')
    if 'trasera' in est['averias']:
        preg.append('¿Solo está roto el cristal de atrás o también las lentes de las cámaras?')
    if 'cámara' in est['extras']:
        preg.append('¿Qué le pasa exactamente a la cámara: no enfoca, se ve borrosa o está negra?')
    if not a.get('bateria'):
        preg.append('¿Qué salud tiene la batería?' + (' (Ajustes › Batería › Estado)' if iphone else ''))
    preg.append('¿Funciona el Face ID?' if iphone else '¿Funciona la huella?')
    preg.append('¿Se ha abierto o reparado alguna vez? ¿Qué piezas se cambiaron?')
    if not re.search(r'\bcaja\b|factura', a['descripcion'], re.I):
        preg.append('¿Tiene caja o factura?')
    preg.append('¿Has quitado ya tu cuenta de ' + ('iCloud' if iphone else 'Google') + '? ¿Es libre de operador?')
    preg = preg[:6]

    if d['tipo'] == 'reparar':
        regateo = (f"Empieza en {d['oferta']} € diciendo que hay que reparar "
                   f"({', '.join(d['reparacion'])}). Si contraofrece, cierra entre {d['oferta']} y {d['max_pagar']} €. "
                   f"No pases de {d['max_pagar']} €.")
    else:
        regateo = (f"Ofrece {d['oferta']} € recogiéndolo en mano hoy. Si en persona ves marcas, batería por debajo "
                   f"del 85 % o algo que no decía, úsalo para no subir. Tope {d['max_pagar']} €.")
    mensaje = (f"Hola, me interesa el {a['modelo']}. ¿Sigue disponible? {preg[0]} "
               f"Si está como dices te puedo ofrecer {d['oferta']} € y lo recojo en mano cuando te venga bien.")
    return resumen, preg, regateo, mensaje
