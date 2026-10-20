"""Ajustes del Radar de chollos. Cambia aquí los criterios sin tocar el resto del código."""

# Punto de partida para distancias y búsquedas (Fuenlabrada, Madrid)
ORIGEN = (40.2842, -3.7942)
ORIGEN_NOMBRE = 'Fuenlabrada'
RADIO_KM = 60            # radio de búsqueda en Wallapop
PRECIO_MAX = 600         # por encima de esto no es chollo
PRECIO_MIN = 30          # por debajo casi siempre es piezas o trampa
PRECIO_MAX_BUSQUEDA = 1200  # se buscan hasta aquí para conocer el precio de mercado de cada modelo

# Beneficio mínimo que tiene que dejar un anuncio para avisar (euros netos)
BENEFICIO_MIN = {
    ('iphone', 'listo'): 25,
    ('iphone', 'reparar'): 40,
    ('android', 'listo'): 60,     # Android solo si es un chollo de verdad
    ('android', 'reparar'): 80,
}
VENTA_FACTOR = 0.90      # se vende ~10 % por debajo de la mediana de anuncios
COSTE_FIJO = {'listo': 5, 'reparar': 10}   # transporte, limpieza, protector, adhesivo
MARGEN_REGATEO = 0.93    # avisar solo si regateando ~7 % (o menos) se llega al máximo
MARGEN_VIGILAR = 0.78    # entre 7 % y 28 % por encima del máximo: se vigila por si baja de precio

# Búsquedas en cada revisión (order_by=newest dentro del radio)
BUSQUEDAS = [
    ('iphone', 3),
    ('iphone roto', 1), ('iphone pantalla rota', 1), ('iphone para reparar', 1),
    ('samsung galaxy', 2), ('google pixel', 1), ('xiaomi', 1),
]

# Horas en las que los avisos llegan sin sonido (hora de Madrid)
SILENCIO = (0, 8)        # de 0:00 a 7:59

# Días que un chollo sigue en la página y se comprueba si se vende o baja de precio
DIAS_ACTIVO = 5

# ---------------------------------------------------------------------------
# Coste de reparación por modelo de iPhone (pieza de buena calidad + material).
# pantalla: OLED "sin mensaje"/soft OLED (LCD en XR/11/SE). trasera: carcasa o tapa;
# 'laser' = el cristal va pegado y hay que ir a taller (precio de taller).
# Precios orientativos de tiendas de repuestos españolas, octubre 2026.
# Precios de pieza (IVA incluido) en tiendas para reparadores como 5G-M o en AliExpress/Amazon:
# pantalla = soft OLED o incell de buena calidad, batería compatible, trasera = cristal o tapa.
# iFixit vende lo mismo con garantía y herramientas pero ~2 veces más caro.
# Cuando apuntéis reparaciones reales en el registro de la web, el bot usa vuestros costes en vez de estos.
IPHONE_PIEZAS = {
    #             pantalla bateria trasera  trasera_tipo
    'SE':        (25, 18, 25, 'carcasa'),
    'X':         (40, 18, 100, 'laser'),
    'XS':        (40, 18, 100, 'laser'),
    'XS Max':    (50, 20, 100, 'laser'),
    'XR':        (30, 18, 100, 'laser'),
    '11':        (30, 18, 100, 'laser'),
    '11 Pro':    (45, 20, 100, 'laser'),
    '11 Pro Max':(55, 22, 110, 'laser'),
    '12 mini':   (55, 20, 30, 'carcasa'),
    '12':        (45, 23, 25, 'carcasa'),
    '12 Pro':    (45, 23, 40, 'carcasa'),
    '12 Pro Max':(60, 25, 50, 'carcasa'),
    '13 mini':   (60, 22, 100, 'laser'),
    '13':        (50, 22, 100, 'laser'),
    '13 Pro':    (60, 24, 120, 'laser'),
    '13 Pro Max':(65, 25, 120, 'laser'),
    '14':        (50, 24, 35, 'tapa'),
    '14 Plus':   (60, 25, 40, 'tapa'),
    '14 Pro':    (80, 26, 130, 'laser'),
    '14 Pro Max':(90, 28, 130, 'laser'),
    '15':        (70, 28, 45, 'tapa'),
    '15 Plus':   (80, 30, 50, 'tapa'),
    '15 Pro':    (100, 30, 50, 'tapa'),
    '15 Pro Max':(110, 32, 55, 'tapa'),
    '16e':       (80, 30, 50, 'tapa'),
    '16':        (90, 30, 50, 'tapa'),
    '16 Plus':   (100, 32, 55, 'tapa'),
    '16 Pro':    (130, 35, 60, 'tapa'),
    '16 Pro Max':(140, 38, 65, 'tapa'),
}
IPHONE_POR_DEFECTO = (90, 30, 60, 'tapa')

# Android: coste aproximado por gama (pantalla original/Service Pack, batería, tapa)
ANDROID_PIEZAS = {
    'samsung_s_ultra': (190, 22, 15),
    'samsung_s':     (130, 20, 12),
    'samsung_s_fe':  (100, 20, 12),
    'samsung_a':     (65, 18, 10),
    'pixel':         (80, 18, 25),
    'pixel_pro':     (110, 20, 30),
    'xiaomi':        (55, 18, 15),
}

# Coste de fallos pequeños que pueden venir además de la avería principal
EXTRAS = {
    'cámara': 45,
    'puerto de carga': 12,
    'altavoz': 12,
    'botón': 10,
}

# ---------------------------------------------------------------- memoria del mercado
# El bot sigue los anuncios que ve (aunque no sean chollos) y apunta cuándo desaparecen
# para saber a qué precio se venden de verdad y cuántos días tardan.
MERCADO_MAX_SEGUIDOS = 5000     # anuncios de iPhone seguidos a la vez
MERCADO_REVISAR_POR_VEZ = 150   # cuántos comprueba en cada pasada (cada uno se mira cada pocas horas)
MERCADO_DIAS_SEGUIR = 30        # si sigue a la venta tras estos días, se apunta como "no vendido"
MERCADO_DIAS_ESTUDIO = 120      # ventana del estudio de mercado
MERCADO_MIN_VENTAS = 5          # ventas vistas necesarias para fiarse del precio real de venta

# Lo que aprende de vuestras ventas reales (registro de la web)
APRENDER_MIN_VENTAS = 3         # ventas vuestras necesarias para ajustar el precio de venta

# Resumen diario en Telegram (hora de Madrid)
RESUMEN_HORA = 21
