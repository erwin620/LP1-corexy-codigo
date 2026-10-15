# -*- coding: utf-8 -*-
"""Valida las macros de pi-config/ como lo haria Klipper.

Uso:   python pi-config/tests/validar_macros.py pi-config

NO sustituye a la prueba en maquina: no sabe de mecanica, de pasos perdidos
ni de StallGuard. Sirve para no subir a la Pi algo que ni siquiera arranca,
o que mueve un eje al reves (ver el bug del signo, feature 011).

1) Compila TODAS las plantillas jinja de los campos gcode: (sintaxis).
2) Renderiza las macros tocadas por la feature 011 con un 'printer' falso,
   comprobando que emiten (o no emiten) los comandos esperados.

Klipper crea el entorno asi (klippy/extras/gcode_macro.py):
    jinja2.Environment('{%', '%}', '{', '}', extensions=['jinja2.ext.do'])
"""
import sys, os, configparser
try:
    import jinja2
except ImportError:
    sys.exit('Falta jinja2:  python -m pip install jinja2   (o instalalo aparte con --target ./pylibs y exporta PYTHONPATH=./pylibs)')

CFG = sys.argv[1]
env = jinja2.Environment('{%', '%}', '{', '}', extensions=['jinja2.ext.do'])

class RaiseError(Exception):
    pass

def action_raise_error(msg):
    raise RaiseError(msg)

def action_respond_info(msg):
    return ''

def action_emergency_stop(msg=''):
    raise RaiseError('emergency stop')

BASE_CTX = {
    'action_raise_error': action_raise_error,
    'action_respond_info': action_respond_info,
    'action_emergency_stop': action_emergency_stop,
    'action_call_remote_method': lambda *a, **k: '',
    'params': {},
    'rawparams': '',
}

# ---------- 1. cargar todas las macros ----------
macros = {}      # nombre -> texto del campo gcode
variables = {}   # nombre -> {var: valor}
files = [f for f in os.listdir(CFG) if f.endswith('.cfg')]
for fn in sorted(files):
    cp = configparser.RawConfigParser(strict=False, inline_comment_prefixes=(';', '#'))
    cp.read(os.path.join(CFG, fn), encoding='utf-8')
    for sec in cp.sections():
        if not (sec.startswith('gcode_macro ') or sec.startswith('delayed_gcode ')):
            continue
        name = sec.split(' ', 1)[1]
        if cp.has_option(sec, 'gcode'):
            macros[name] = (fn, cp.get(sec, 'gcode'))
        variables[name] = {}
        for opt in cp.options(sec):
            if opt.startswith('variable_'):
                raw = cp.get(sec, opt)
                try:
                    val = eval(raw, {}, {})
                except Exception:
                    val = raw
                variables[name][opt[len('variable_'):]] = val

# ---------- 2. compilar todas (sintaxis) ----------
errores = 0
for name, (fn, src) in sorted(macros.items()):
    try:
        env.from_string(src)
    except jinja2.TemplateError as e:
        errores += 1
        print('SINTAXIS  %-28s %-20s %s' % (name, fn, e))
print('[1] compiladas %d macros de %d archivos -> %d errores de sintaxis'
      % (len(macros), len(files), errores))
if errores:
    sys.exit(1)

# ---------- 3. render con un printer falso ----------
class Obj(dict):
    """dict accesible por atributo, como los objetos de status de Klipper."""
    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError:
            raise AttributeError(k)

def printer_falso(save_vars, marco_homed=1, index_homed=1, running=0,
                  homed_axes='xy', marco_pos=1, x=280.0):
    """marco_pos: 0 = DESCONOCIDA, 1 = ARRIBA, 2 = ABAJO (feature 012).
    x: posicion del squeegee en el sistema de coordenadas del gcode; 280 es
    el tope de arriba (position_endstop de stepper_x)."""
    p = Obj()
    p['save_variables'] = Obj(variables=Obj(save_vars))
    p['toolhead'] = Obj(homed_axes=homed_axes)
    # gcode_move.gcode_position es lo que leen las guardas del squeegee: es el
    # sistema de coordenadas de los G1 X, no la posicion cruda del toolhead.
    p['gcode_move'] = Obj(gcode_position=Obj(x=x, y=0.0, z=0.0, e=0.0))
    for nombre, vars_ in variables.items():
        p['gcode_macro ' + nombre] = Obj(vars_)
    p['gcode_macro _MARCO']['homed'] = marco_homed
    p['gcode_macro _MARCO']['pos'] = marco_pos
    p['gcode_macro _INDEX']['homed'] = index_homed
    p['gcode_macro _CYCLE_STATE']['running'] = running
    p['configfile'] = Obj(settings={
        'manual_stepper marco': Obj(rotation_distance=40, velocity=10, accel=2000),
        'tmc5160 manual_stepper marco': Obj(run_current=1.2, driver_sgt=6),
        'manual_stepper index': Obj(velocity=180, accel=1500),
        'stepper_x': Obj(position_endstop=280.0, position_min=-300.0, position_max=300.0),
        'stepper_y': Obj(position_endstop=0.0, position_min=0.0, position_max=200.0),
    })
    return p

VARS_OFF = {'modo_carrusel': 1, 'pos_left': 0.0, 'pos_right': 100.0,
            'squeegee_down': -125.0, 'squeegee_speed': 8000.0,
            'squeegee_up': 280.0, 'start_side': 0, 'stroke_speed': 7500.0,
            'simular_impresion': 0}
VARS_ON = dict(VARS_OFF, marco_en_ciclo=1)

def render(nombre, printer, params=None, rawparams=''):
    ctx = dict(BASE_CTX)
    ctx['printer'] = printer
    ctx['params'] = params or {}
    ctx['rawparams'] = rawparams
    return env.from_string(macros[nombre][1]).render(ctx)

def cmds(texto):
    out = []
    for ln in texto.splitlines():
        ln = ln.strip()
        if ln and not ln.startswith('#') and not ln.startswith(';'):
            out.append(ln)
    return out

fallos = []
total = [0]
def check(titulo, cond, detalle=''):
    total[0] += 1
    print(('  OK   ' if cond else '  FALLA') + '  ' + titulo + (('  <- ' + detalle) if (detalle and not cond) else ''))
    if not cond:
        fallos.append(titulo)

print('\n[2] comportamiento con el marco APAGADO (default, sin la variable)')
sal = cmds(render('_MARCO_BAJAR', printer_falso(VARS_OFF, marco_homed=0)))
check('_MARCO_BAJAR no emite NADA sin marco_en_ciclo', sal == [], repr(sal))
sal = cmds(render('_MARCO_SUBIR', printer_falso(VARS_OFF, marco_homed=0)))
check('_MARCO_SUBIR no emite NADA sin marco_en_ciclo', sal == [], repr(sal))
sal = cmds(render('PRINT_CYCLE', printer_falso(VARS_OFF)))
check('PRINT_CYCLE (feature 013) = _EMBARRAR y luego _IMPRIMIR_PASADA',
      sal == ['_EMBARRAR', '_IMPRIMIR_PASADA'], repr(sal))
def ciclo_completo(pf):
    return cmds(render('_EMBARRAR', pf)) + cmds(render('_IMPRIMIR_PASADA', pf))
sal = ciclo_completo(printer_falso(VARS_OFF))
esperado = ['G1 Y100.0    F7500.0',
            '_MARCO_BAJAR',
            'G1 X-125.0  F8000.0',
            'G1 Y0.0  F7500.0',
            'G1 X280.0    F8000.0',
            '_MARCO_SUBIR']
solo_g = [c.split(';')[0].strip() for c in sal if c != 'G90']
check('feature 013: embarre PRIMERO (marco arriba), luego marco baja y los 3 movimientos de siempre',
      solo_g == esperado, repr(solo_g))
sal = cmds(render('_IMPRIMIR_PASADA', printer_falso(VARS_OFF)))
check('_IMPRIMIR_PASADA no emite el stroke de ida (el embarre ya se hizo)',
      not any(c.startswith('G1 Y100') for c in sal), repr(sal))
for side, esp in [(0, '0.0'), (1, '100.0')]:
    sal = cmds(render('START', printer_falso(dict(VARS_OFF, start_side=side)), params={}))
    movs = [c.split(';')[0].strip() for c in sal if c.startswith('G1 ')]
    check('feature 014: START lleva la cabeza al lado de espera (start_side=%d -> Y%s)' % (side, esp),
          len(movs) == 1 and movs[0].startswith('G1 Y' + esp + ' '), repr(movs))
sal = cmds(render('SET_CYCLE', printer_falso(VARS_OFF), params={'ESPERA': 'DERECHA'}))
check('feature 014: SET_CYCLE ESPERA=DERECHA guarda espera_derecha=1 y NO toca start_side',
      'SAVE_VARIABLE VARIABLE=espera_derecha VALUE=1' in sal and not any('start_side' in c for c in sal), repr(sal))
sal = cmds(render('SET_CYCLE', printer_falso(VARS_OFF), params={'ESPERA': 'IZQUIERDA'}))
check('feature 014: SET_CYCLE ESPERA=IZQUIERDA guarda espera_derecha=0',
      'SAVE_VARIABLE VARIABLE=espera_derecha VALUE=0' in sal, repr(sal))
# Con espera DERECHA el sentido del stroke NO cambia: embarre a 100, imprime a 0.
pfd = printer_falso(dict(VARS_OFF, espera_derecha=1))
solo_y = [' '.join(c.split()[:2]) for c in cmds(render('_EMBARRAR', pfd)) + cmds(render('_IMPRIMIR_PASADA', pfd)) if c.startswith('G1 Y')]
check('feature 014: ESPERA DERECHA no invierte el stroke (embarre a Y100, imprime a Y0)',
      solo_y == ['G1 Y100.0', 'G1 Y0.0'], repr(solo_y))
# ---- feature 015: marco y squeegee a la vez -------------------------------
def pasada(**extra):
    pf = printer_falso(dict(VARS_ON, **extra), marco_homed=1)
    return [' '.join(c.split(';')[0].split()) for c in cmds(render('_IMPRIMIR_PASADA', pf)) if c != 'G90']
SECUENCIAL = ['_MARCO_BAJAR', 'G1 X-125.0 F8000.0', 'G1 Y0.0 F7500.0', 'G1 X280.0 F8000.0', '_MARCO_SUBIR']
sal = [c for c in cmds(render('_IMPRIMIR_PASADA', printer_falso(VARS_OFF))) if c != 'G90']
check('feature 015: con MARCO=NO no hay marco que mover a la vez (squeegee solo)',
      not any('SYNC' in c or 'ESPERAR' in c for c in sal) and '_MARCO_BAJAR' in sal, repr(sal))
esperado = ['_MARCO_BAJAR SYNC=0', 'G1 X-125.0 F8000.0', '_MARCO_ESPERAR_ABAJO', 'G1 Y0.0 F7500.0',
            'G1 X-115.0 F8000.0', '_MARCO_SUBIR SYNC=0', 'G1 X280.0 F8000.0', '_MARCO_ESPERAR_ARRIBA']
check('feature 015: con MARCO=SI es lo NORMAL (sin interruptor): marco encolado ANTES del G1 al bajar; el squeegee suelta ANTES de arrancar el marco al subir',
      pasada() == esperado, repr(pasada()))
sal = pasada(marco_speed=50.0)
check('feature 015: guarda de tiempos: marco demasiado lento -> cae a SECUENCIAL y avisa',
      [c for c in sal if not c.startswith('M118')] == SECUENCIAL and any(c.startswith('M118 AVISO') for c in sal), repr(sal))
# El sentido de "arriba" sale de stepper_x, no se asume: con el home al MINIMO el tramo de salida va hacia numeros MAS BAJOS.
pf = printer_falso(dict(VARS_ON, squeegee_up=-280.0, squeegee_down=125.0), marco_homed=1, x=-280.0)
pf['configfile']['settings']['stepper_x'] = Obj(position_endstop=-300.0, position_min=-300.0, position_max=300.0)
sal = [' '.join(c.split(';')[0].split()) for c in cmds(render('_IMPRIMIR_PASADA', pf))]
check('feature 015: con el home de X al minimo el tramo de salida va hacia el lado correcto (125 -> 115)',
      'G1 X115.0 F8000.0' in sal, repr(sal))
sal = cmds(render('_MARCO_GO_ABAJO', printer_falso(VARS_ON), params={'SYNC': '0'}))
check('feature 015: _MARCO_GO_ABAJO SYNC=0 encola sin M400 y deja pos=0 (DESCONOCIDA)',
      any(c.endswith('SYNC=0') and 'MOVE=-110.0' in c for c in sal) and 'M400' not in sal
      and 'SET_GCODE_VARIABLE MACRO=_MARCO VARIABLE=pos VALUE=2' not in sal, repr(sal))
sal = cmds(render('_MARCO_GO_ARRIBA', printer_falso(VARS_ON), params={'SYNC': '0'}))
check('feature 015: _MARCO_GO_ARRIBA SYNC=0 encola sin M400 y deja pos=0',
      any(c.endswith('SYNC=0') and 'MOVE=0.0' in c for c in sal) and 'M400' not in sal
      and 'SET_GCODE_VARIABLE MACRO=_MARCO VARIABLE=pos VALUE=1' not in sal, repr(sal))
for nom, val in [('_MARCO_ESPERAR_ABAJO', 2), ('_MARCO_ESPERAR_ARRIBA', 1)]:
    sal = cmds(render(nom, printer_falso(VARS_ON, marco_homed=1)))
    check('feature 015: %s espera con SYNC=1, M400 y apunta pos=%d' % (nom, val),
          sal == ['MANUAL_STEPPER STEPPER=marco SYNC=1', 'M400',
                  'SET_GCODE_VARIABLE MACRO=_MARCO VARIABLE=pos VALUE=%d' % val], repr(sal))
    check('feature 015: %s no hace nada con MARCO=NO' % nom,
          cmds(render(nom, printer_falso(VARS_OFF, marco_homed=1))) == [])
    check('feature 015: %s no hace nada sin home del marco' % nom,
          cmds(render(nom, printer_falso(VARS_ON, marco_homed=0))) == [])
sal = cmds(render('_MARCO_SUBIR', printer_falso(VARS_ON, marco_homed=0), params={'SYNC': '0'}))
check('feature 015: _MARCO_SUBIR SYNC=0 sin home avisa y NO mueve (como siempre)',
      len(sal) == 1 and sal[0].startswith('M118 AVISO'), repr(sal))
check('feature 015: ya no existe el interruptor BAJADA (la simultanea es lo normal)',
      'movs_juntos' not in macros['SET_CYCLE'][1] and 'BAJADA' not in macros['SET_CYCLE'][1]
      and 'movs_juntos' not in macros['_IMPRIMIR_PASADA'][1])
for mal, motivo in [({'SQUEEGEE_SUELTA': '0'}, 'SQUEEGEE_SUELTA cero'),
                    ({'SQUEEGEE_SUELTA': '-3'}, 'SQUEEGEE_SUELTA negativa'), ({'SQUEEGEE_SUELTA': '999'}, 'SQUEEGEE_SUELTA mayor que el recorrido')]:
    try:
        render('SET_CYCLE', printer_falso(VARS_OFF), params=mal)
        check('feature 015: SET_CYCLE rechaza ' + motivo, False, 'no lanzo error')
    except RaiseError:
        check('feature 015: SET_CYCLE rechaza ' + motivo, True)
sal = cmds(render('SET_CYCLE', printer_falso(VARS_OFF), params={'SQUEEGEE_SUELTA': '8'}))
check('feature 015: SET_CYCLE SQUEEGEE_SUELTA=8 lo guarda',
      any(' '.join(c.split()) == 'SAVE_VARIABLE VARIABLE=squeegee_suelta VALUE=8.0' for c in sal), repr(sal))
try:
    render('SHOW_CYCLE', printer_falso(VARS_ON))
    render('SHOW_CYCLE', printer_falso(VARS_OFF))
    check('feature 015: SHOW_CYCLE renderiza con y sin marco', True)
except Exception as e:
    check('feature 015: SHOW_CYCLE renderiza con y sin marco', False, str(e))

def tick(side, fase, part, sim=0):
    pf = printer_falso(dict(VARS_OFF, espera_derecha=side, simular_impresion=sim))
    pf['gcode_macro _CYCLE_STATE'].update(stop_req=0, count=0, target=0)
    pf['gcode_macro _CAROUSEL']['fase'] = fase
    pf['gcode_macro _INDEX']['part'] = part
    return cmds(render('_carousel_loop', pf))
sal = tick(0, 0, 0)
check('feature 014: IZQUIERDA, paso A: gira CON embarre (013, sin cambios)',
      '_INDEX_AVANZAR_UNA EMBARRAR=1' in sal, repr(sal))
sal = tick(0, 1, 1)
check('feature 014: IZQUIERDA, paso B: solo _IMPRIMIR_PASADA (sin embarre)',
      '_EMBARRAR' not in sal and '_IMPRIMIR_PASADA' in sal, repr(sal))
sal = tick(1, 0, 0)
check('feature 014: DERECHA, paso A: gira SIN embarre (la cabeza se queda quieta)',
      '_INDEX_AVANZAR_UNA' in sal and not any('EMBARRAR' in c for c in sal), repr(sal))
sal = tick(1, 1, 1)
i1 = sal.index('_EMBARRAR') if '_EMBARRAR' in sal else -1
i2 = sal.index('_IMPRIMIR_PASADA') if '_IMPRIMIR_PASADA' in sal else -1
check('feature 014: DERECHA, paso B con prenda: _EMBARRAR y LUEGO _IMPRIMIR_PASADA',
      0 <= i1 < i2, repr(sal))
sal = tick(1, 1, 0)
check('feature 014: DERECHA, estacion sin prenda: no mueve la cabeza',
      '_EMBARRAR' not in sal and '_IMPRIMIR_PASADA' not in sal, repr(sal))
sal = tick(1, 1, 1, sim=1)
check('feature 014: DERECHA con SIMULAR=1: no embarra ni imprime',
      '_EMBARRAR' not in sal and '_IMPRIMIR_PASADA' not in sal, repr(sal))
try:
    render('START', printer_falso(VARS_OFF, marco_homed=0), params={})
    check('START arranca con el marco sin home cuando MARCO=NO', True)
except RaiseError as e:
    check('START arranca con el marco sin home cuando MARCO=NO', False, str(e))

print('\n[3] comportamiento con el marco ENCENDIDO (MARCO=SI)')
# Desde la feature 012 el movimiento vive en _MARCO_GO_*, asi que estas dos
# solo delegan. Se comprueban las dos cosas: que delegan, y que lo que hay al
# otro lado emite EXACTAMENTE el mismo movimiento que emitian ellas antes.
sal = cmds(render('_MARCO_BAJAR', printer_falso(VARS_ON, marco_homed=1)))
check('_MARCO_BAJAR delega en _MARCO_GO_ABAJO', sal == ['_MARCO_GO_ABAJO'], repr(sal))
sal = cmds(render('_MARCO_SUBIR', printer_falso(VARS_ON, marco_homed=1)))
check('_MARCO_SUBIR delega en _MARCO_GO_ARRIBA', sal == ['_MARCO_GO_ARRIBA'], repr(sal))
sal = cmds(render('_MARCO_GO_ABAJO', printer_falso(VARS_ON)))
check('_MARCO_GO_ABAJO baja a -110 a 1000/3000 y apunta la posicion',
      sal == ['SET_GCODE_VARIABLE MACRO=_MARCO VARIABLE=pos VALUE=0',
              'MANUAL_STEPPER STEPPER=marco ENABLE=1',
              'MANUAL_STEPPER STEPPER=marco MOVE=-110.0 SPEED=1000.0 ACCEL=3000.0',
              'M400',
              'SET_GCODE_VARIABLE MACRO=_MARCO VARIABLE=pos VALUE=2'], repr(sal))
sal = cmds(render('_MARCO_GO_ARRIBA', printer_falso(VARS_ON)))
check('_MARCO_GO_ARRIBA vuelve a 0.0 a 1000/3000 y apunta la posicion',
      sal == ['SET_GCODE_VARIABLE MACRO=_MARCO VARIABLE=pos VALUE=0',
              'MANUAL_STEPPER STEPPER=marco ENABLE=1',
              'MANUAL_STEPPER STEPPER=marco MOVE=0.0 SPEED=1000.0 ACCEL=3000.0',
              'M400',
              'SET_GCODE_VARIABLE MACRO=_MARCO VARIABLE=pos VALUE=1'], repr(sal))
try:
    render('_MARCO_BAJAR', printer_falso(VARS_ON, marco_homed=0))
    check('_MARCO_BAJAR ABORTA si el marco no tiene home', False, 'no lanzo error')
except RaiseError as e:
    check('_MARCO_BAJAR ABORTA si el marco no tiene home', 'NO tiene HOME' in str(e))
sal = cmds(render('_MARCO_SUBIR', printer_falso(VARS_ON, marco_homed=0)))
check('_MARCO_SUBIR avisa y NO mueve si no hay home',
      len(sal) == 1 and sal[0].startswith('M118 AVISO'), repr(sal))
try:
    render('START', printer_falso(VARS_ON, marco_homed=0), params={})
    check('START BLOQUEADO con MARCO=SI y el marco sin home', False, 'no lanzo error')
except RaiseError as e:
    check('START BLOQUEADO con MARCO=SI y el marco sin home', 'marco' in str(e).lower())
try:
    render('START', printer_falso(VARS_ON, marco_homed=1), params={})
    check('START arranca con MARCO=SI y el marco homeado', True)
except RaiseError as e:
    check('START arranca con MARCO=SI y el marco homeado', False, str(e))
sal = cmds(render('_MARCO_GO_ABAJO', printer_falso(dict(VARS_ON, marco_abajo=60.0,
                                                       marco_speed=500.0, marco_accel=1200.0))))
check('el movimiento del marco respeta los valores guardados por el operador',
      'MOVE=-60.0 SPEED=500.0 ACCEL=1200.0' in ' '.join(sal), repr(sal))
sal = cmds(render('_MARCO_GO_ARRIBA', printer_falso(dict(VARS_ON, marco_arriba=-2.0))))
check('marco_arriba negativo deja margen antes de la pared',
      'MOVE=-2.0' in ' '.join(sal), repr(sal))
# El techo anti-tecleo se movio a _MARCO_GO_ABAJO con el refactor: sigue vivo.
try:
    render('_MARCO_GO_ABAJO', printer_falso(dict(VARS_ON, marco_abajo=999.0)))
    check('el movimiento del marco rechaza pasar del techo abajo_max', False, 'no lanzo error')
except RaiseError as e:
    check('el movimiento del marco rechaza pasar del techo abajo_max', 'techo' in str(e))

print('\n[4] SET_CYCLE / SHOW_CYCLE / invalidacion del home')
sal = cmds(render('SET_CYCLE', printer_falso(VARS_OFF), params={'MARCO': 'SI'}))
check('SET_CYCLE MARCO=SI guarda marco_en_ciclo=1',
      'SAVE_VARIABLE VARIABLE=marco_en_ciclo VALUE=1' in sal, repr(sal))
sal = cmds(render('SET_CYCLE', printer_falso(VARS_ON), params={'MARCO': 'NO'}))
check('SET_CYCLE MARCO=NO guarda marco_en_ciclo=0',
      'SAVE_VARIABLE VARIABLE=marco_en_ciclo VALUE=0' in sal, repr(sal))
for mal, motivo in [({'MARCO': 'QUIZA'}, 'MARCO invalido'),
                    ({'MARCO_ABAJO': '999'}, 'MARCO_ABAJO pasa del techo'),
                    ({'MARCO_ABAJO': '0'}, 'MARCO_ABAJO cero'),
                    ({'MARCO_ARRIBA': '5'}, 'MARCO_ARRIBA positivo'),
                    ({'MARCO_SPEED': '0'}, 'MARCO_SPEED cero')]:
    try:
        render('SET_CYCLE', printer_falso(VARS_ON), params=mal)
        check('SET_CYCLE rechaza ' + motivo, False, 'no lanzo error')
    except RaiseError:
        check('SET_CYCLE rechaza ' + motivo, True)
sal = cmds(render('SET_CYCLE', printer_falso(VARS_ON), params={'POS_LEFT': '5'}))
check('SET_CYCLE con parametros de siempre sigue funcionando',
      any(' '.join(c.split()) == 'SAVE_VARIABLE VARIABLE=pos_left VALUE=5.0' for c in sal), repr(sal))
try:
    render('SHOW_CYCLE', printer_falso(VARS_ON))
    render('SHOW_CYCLE', printer_falso(VARS_OFF))
    check('SHOW_CYCLE renderiza con el marco ON y OFF', True)
except Exception as e:
    check('SHOW_CYCLE renderiza con el marco ON y OFF', False, str(e))
sal = cmds(render('_INVALIDAR_HOMES', printer_falso(VARS_ON, marco_homed=1)))
check('M84 invalida tambien el home del marco',
      'SET_GCODE_VARIABLE MACRO=_MARCO VARIABLE=homed VALUE=0' in sal, repr(sal))
sal = cmds(render('MARCO_TEST', printer_falso(VARS_ON), params={}))
check('MARCO_TEST invalida el home del marco',
      'SET_GCODE_VARIABLE MACRO=_MARCO VARIABLE=homed VALUE=0' in sal, repr(sal))
sal = cmds(render('MARCO_OFF', printer_falso(VARS_ON)))
check('MARCO_OFF invalida el home del marco',
      'SET_GCODE_VARIABLE MACRO=_MARCO VARIABLE=homed VALUE=0' in sal, repr(sal))
sal = cmds(render('MARCO_HOME', printer_falso(VARS_ON)))
check('MARCO_HOME valida el home al final',
      sal.index('SET_GCODE_VARIABLE MACRO=_MARCO VARIABLE=homed VALUE=1')
      > sal.index('MANUAL_STEPPER STEPPER=marco MOVE=500.0 SPEED=100.0 ACCEL=100 STOP_ON_ENDSTOP=home'),
      repr(sal))
try:
    render('MARCO_ARRIBA', printer_falso(VARS_ON, marco_homed=1, running=1))
    check('MARCO_ARRIBA se rechaza con el ciclo en marcha', False, 'no lanzo error')
except RaiseError:
    check('MARCO_ARRIBA se rechaza con el ciclo en marcha', True)

print('\n[5] feature 012 - pantalla MANUAL')

# --- requisito: MARCO_ABAJO/MARCO_ARRIBA mueven SIEMPRE, tambien con MARCO=NO ---
sal = cmds(render('MARCO_ABAJO', printer_falso(VARS_OFF, marco_homed=1)))
check('MARCO_ABAJO mueve aunque marco_en_ciclo=0 (los botones siempre funcionan)',
      sal == ['_MARCO_GO_ABAJO', 'M118 Marco abajo.'], repr(sal))
try:
    render('MARCO_ABAJO', printer_falso(VARS_OFF, marco_homed=0))
    check('MARCO_ABAJO se rechaza sin home del marco', False, 'no lanzo error')
except RaiseError as e:
    check('MARCO_ABAJO se rechaza sin home del marco', 'HOME' in str(e))
try:
    render('MARCO_ABAJO', printer_falso(VARS_OFF, marco_homed=1, running=1))
    check('MARCO_ABAJO se rechaza con el ciclo en marcha', False, 'no lanzo error')
except RaiseError:
    check('MARCO_ABAJO se rechaza con el ciclo en marcha', True)

# --- equivalencia manual <-> automatico: mismas 4 lineas del ciclo (_EMBARRAR + _IMPRIMIR_PASADA) ---
ciclo = ciclo_completo(printer_falso(VARS_OFF))
g_ciclo = [c.split(';')[0].strip() for c in ciclo if c not in ('G90',) and not c.startswith('_MARCO')]
norm = lambda s: ' '.join(s.split())
manual_esperado = {
    'MANUAL_STROKE_OUT':     g_ciclo[0],   # paso 1: viaje en vacio
    'MANUAL_SQUEEGEE_DOWN':  g_ciclo[1],   # paso 2
    'MANUAL_STROKE_IN':      g_ciclo[2],   # paso 3: la pasada que imprime
}
p_manual_ok = printer_falso(VARS_OFF, marco_pos=2, x=280.0)  # marco abajo: no bloquea el stroke
for macro, esperado in manual_esperado.items():
    sal = cmds(render(macro, p_manual_ok))
    g = [c for c in sal if c.startswith('G1 ')]
    check(macro + ' emite el MISMO movimiento que su paso de PRINT_CYCLE',
          len(g) == 1 and norm(g[0]) == norm(esperado),
          repr(g) + ' vs ' + repr(esperado))
# Paso 4: desde 2026-09-25 MANUAL_SQUEEGEE_UP delega en _SQUEEGEE_A_ARRIBA
# (nunca baja). Desde abajo tiene que emitir el mismo G1 que PRINT_CYCLE.
sal = cmds(render('MANUAL_SQUEEGEE_UP', p_manual_ok))
check('MANUAL_SQUEEGEE_UP delega en _SQUEEGEE_A_ARRIBA', '_SQUEEGEE_A_ARRIBA' in sal, repr(sal))
g = [c for c in cmds(render('_SQUEEGEE_A_ARRIBA', printer_falso(VARS_OFF, x=-125.0))) if c.startswith('G1 ')]
check('_SQUEEGEE_A_ARRIBA desde abajo emite el MISMO movimiento que el paso 4 de PRINT_CYCLE',
      len(g) == 1 and norm(g[0]) == norm(g_ciclo[3]), repr(g) + ' vs ' + repr(g_ciclo[3]))

# --- guardas de las 4 macros manuales ---
for macro in list(manual_esperado) + ['MANUAL_SQUEEGEE_UP']:
    try:
        render(macro, printer_falso(VARS_OFF, running=1))
        check(macro + ' se rechaza con el ciclo automatico en marcha', False, 'no lanzo error')
    except RaiseError:
        check(macro + ' se rechaza con el ciclo automatico en marcha', True)
    try:
        render(macro, printer_falso(VARS_OFF, homed_axes=''))
        check(macro + ' se rechaza sin HOME', False, 'no lanzo error')
    except RaiseError as e:
        check(macro + ' se rechaza sin HOME', 'HOME' in str(e))

# --- MANUAL_SQUEEGEE_DOWN: solo baja con el marco ABAJO de verdad ---
try:
    render('MANUAL_SQUEEGEE_DOWN', printer_falso(VARS_OFF, marco_pos=1))
    check('MANUAL_SQUEEGEE_DOWN se rechaza con el marco ARRIBA', False, 'no lanzo error')
except RaiseError as e:
    check('MANUAL_SQUEEGEE_DOWN se rechaza con el marco ARRIBA', 'ARRIBA' in str(e))
try:
    render('MANUAL_SQUEEGEE_DOWN', printer_falso(VARS_OFF, marco_pos=0))
    check('MANUAL_SQUEEGEE_DOWN se rechaza con el marco DESCONOCIDO', False, 'no lanzo error')
except RaiseError as e:
    check('MANUAL_SQUEEGEE_DOWN se rechaza con el marco DESCONOCIDO', 'DESCONOCIDA' in str(e))
sal = cmds(render('MANUAL_SQUEEGEE_DOWN', printer_falso(VARS_OFF, marco_pos=2, marco_homed=1)))
check('MANUAL_SQUEEGEE_DOWN baja con el marco ABAJO confirmado',
      any(c.startswith('G1 X') for c in sal), repr(sal))

# --- las dos de stroke: rechazadas con squeegee abajo + marco no confirmado abajo ---
for macro in ('MANUAL_STROKE_OUT', 'MANUAL_STROKE_IN'):
    try:
        render(macro, printer_falso(VARS_OFF, marco_pos=1, x=-125.0))  # squeegee_down real de VARS_OFF
        check(macro + ' se rechaza con el squeegee ABAJO y el marco no abajo', False, 'no lanzo error')
    except RaiseError as e:
        check(macro + ' se rechaza con el squeegee ABAJO y el marco no abajo', 'bloqueado' in str(e).lower())
    sal = cmds(render(macro, printer_falso(VARS_OFF, marco_pos=1, x=280.0)))  # squeegee arriba: no pregunta
    check(macro + ' no pregunta nada con el squeegee ARRIBA',
          any(c.startswith('G1 Y') for c in sal), repr(sal))
    sal = cmds(render(macro, printer_falso(VARS_OFF, marco_pos=2, x=-125.0)))  # squeegee abajo, marco abajo: permitido
    check(macro + ' se permite con squeegee ABAJO y marco ABAJO (flujo normal)',
          any(c.startswith('G1 Y') for c in sal), repr(sal))

# --- guarda del marco en INDEX_NEXT / INDEX_GOTO ---
try:
    render('INDEX_NEXT', printer_falso(VARS_OFF, index_homed=1, marco_pos=2))
    check('INDEX_NEXT se rechaza con el marco ABAJO', False, 'no lanzo error')
except RaiseError as e:
    check('INDEX_NEXT se rechaza con el marco ABAJO', 'MARCO' in str(e))
sal = cmds(render('INDEX_NEXT', printer_falso(VARS_OFF, index_homed=1, marco_pos=0)))
check('INDEX_NEXT NO se bloquea con el marco DESCONOCIDO (no regresion de quien no usa marco)',
      any('_INDEX_AVANZAR_UNA' in c for c in sal), repr(sal))
try:
    render('INDEX_GOTO', printer_falso(VARS_OFF, index_homed=1, marco_pos=2), params={'ESTACION': '2'})
    check('INDEX_GOTO se rechaza con el marco ABAJO', False, 'no lanzo error')
except RaiseError as e:
    check('INDEX_GOTO se rechaza con el marco ABAJO', 'MARCO' in str(e))

# --- guardas de START (requisito 5): bloqueo por marco/squeegee en posicion manual ---
try:
    render('START', printer_falso(VARS_OFF, marco_pos=2), params={})
    check('START se rechaza con el marco ABAJO', False, 'no lanzo error')
except RaiseError as e:
    check('START se rechaza con el marco ABAJO', 'MARCO' in str(e))
sal_ok = True
try:
    render('START', printer_falso(VARS_OFF, marco_pos=0), params={})
except RaiseError as e:
    sal_ok = False
check('START NO se bloquea con el marco DESCONOCIDO (no regresion de MARCO=NO)', sal_ok)
try:
    render('START', printer_falso(VARS_OFF, marco_pos=1, x=-125.0), params={})  # squeegee_down real
    check('START se rechaza con el SQUEEGEE abajo', False, 'no lanzo error')
except RaiseError as e:
    check('START se rechaza con el SQUEEGEE abajo', 'SQUEEGEE' in str(e))
sal_ok = True
try:
    render('START', printer_falso(VARS_OFF, marco_pos=1, x=280.0), params={})  # squeegee arriba
except RaiseError as e:
    sal_ok = False
check('START arranca con marco ARRIBA y squeegee ARRIBA (caso normal)', sal_ok)

print('\n[6] lint: el bug del signo en jinja no debe volver a colarse')
# Klipper crea el entorno jinja con { y } como delimitadores de variable (no
# las dobles llaves habituales), asi que un '-' pegado a la llave de apertura
# es el marcador de control de espacios en blanco, NO un signo menos, y
# MOVE={-1.0 * x} renderiza POSITIVO sin dar ningun error (ver macros_marco.cfg
# y el plan de la feature 011). Cazado aqui de una vez por todas.
sospechosas = []
for name, (fn, src) in sorted(macros.items()):
    if '{-' in src:
        sospechosas.append('%s (%s)' % (name, fn))
check('ninguna macro tiene un "-" pegado a la llave de apertura ({-)',
      not sospechosas, repr(sospechosas))

print('\n[7] "subir el squeegee" nunca lo baja (bug de AJUSTES, 2026-09-25)')
# El caso real: tope en 280, squeegee_up guardado en 25 desde AJUSTES.
VARS_MAL = dict(VARS_OFF, squeegee_up=25.0, squeegee_down=30.0)
sal = cmds(render('_SQUEEGEE_A_ARRIBA', printer_falso(VARS_MAL, x=280.0)))
check('_SQUEEGEE_A_ARRIBA NO baja desde el tope aunque squeegee_up este mal', sal == [], repr(sal))
sal = cmds(render('_SQUEEGEE_A_ARRIBA', printer_falso(VARS_OFF, x=280.0)))
check('_SQUEEGEE_A_ARRIBA no se mueve si ya esta en squeegee_up', sal == [], repr(sal))
sal = cmds(render('_SQUEEGEE_A_ARRIBA', printer_falso(VARS_OFF, x=-54.0)))
check('_SQUEEGEE_A_ARRIBA sube desde abajo', any(c.startswith('G1 X280.0') for c in sal), repr(sal))
for macro in ['_INDEX_SQUEEGEE_ARRIBA', '_SCREEN_SQUEEGEE_ARRIBA']:
    sal = cmds(render(macro, printer_falso(VARS_OFF)))
    check(macro + ' delega en _SQUEEGEE_A_ARRIBA', sal == ['_SQUEEGEE_A_ARRIBA'], repr(sal))
for mal, motivo in [({'SQUEEGEE_UP': '25', 'SQUEEGEE_DOWN': '30'}, 'arriba por debajo de abajo (el caso real)'),
                    ({'SQUEEGEE_UP': '-200'}, 'solo SQUEEGEE_UP, por debajo del abajo ya guardado (-125)'),
                    ({'SQUEEGEE_DOWN': '300'}, 'solo SQUEEGEE_DOWN, por encima del arriba ya guardado'),
                    ({'SQUEEGEE_UP': '-54', 'SQUEEGEE_DOWN': '-54'}, 'arriba igual a abajo'),
                    ({'SQUEEGEE_UP': '400'}, 'fuera de los limites de X')]:
    try:
        sal = cmds(render('SET_CYCLE', printer_falso(VARS_OFF), params=mal))
        check('SET_CYCLE rechaza ' + motivo, False, 'no lanzo error: ' + repr(sal))
    except RaiseError:
        check('SET_CYCLE rechaza ' + motivo, True)
sal = cmds(render('SET_CYCLE', printer_falso(VARS_OFF), params={'SQUEEGEE_UP': '280', 'SQUEEGEE_DOWN': '-54'}))
check('SET_CYCLE acepta 280 / -54',
      any(' '.join(c.split()) == 'SAVE_VARIABLE VARIABLE=squeegee_down VALUE=-54.0' for c in sal), repr(sal))

print('\n[8] revision 2026-10-08: posiciones del stroke, INDEX_HOME, MARCO_HOME, _cycle_loop')
for mal, motivo in [({'POS_LEFT': '-5'}, 'POS_LEFT por debajo de Y min'),
                    ({'POS_RIGHT': '250'}, 'POS_RIGHT por encima de Y max'),
                    ({'POS_LEFT': '100'}, 'POS_LEFT igual al POS_RIGHT ya guardado')]:
    try:
        sal = cmds(render('SET_CYCLE', printer_falso(VARS_OFF), params=mal))
        check('SET_CYCLE rechaza ' + motivo, False, 'no lanzo error: ' + repr(sal))
    except RaiseError:
        check('SET_CYCLE rechaza ' + motivo, True)
sal = cmds(render('SET_CYCLE', printer_falso(VARS_OFF), params={'POS_LEFT': '0', 'POS_RIGHT': '81'}))
check('SET_CYCLE acepta POS_LEFT=0 POS_RIGHT=81 (los valores reales)',
      any(' '.join(c.split()) == 'SAVE_VARIABLE VARIABLE=pos_right VALUE=81.0' for c in sal), repr(sal))
try:
    render('INDEX_HOME', printer_falso(VARS_OFF, marco_pos=2))
    check('INDEX_HOME se rechaza con el marco ABAJO', False, 'no lanzo error')
except RaiseError as e:
    check('INDEX_HOME se rechaza con el marco ABAJO', 'MARCO esta ABAJO' in str(e))
for pos in (0, 1):
    try:
        render('INDEX_HOME', printer_falso(VARS_OFF, marco_pos=pos))
        check('INDEX_HOME NO se bloquea con el marco pos=%d' % pos, True)
    except RaiseError as e:
        check('INDEX_HOME NO se bloquea con el marco pos=%d' % pos, False, str(e))
pf = printer_falso(VARS_OFF)
pf['configfile']['settings']['tmc5160 manual_stepper marco']['driver_sgt'] = 9
sal = cmds(render('MARCO_HOME', pf))
check('MARCO_HOME usa el driver_SGT de printer.cfg (no un 6 fijo)',
      'SET_TMC_FIELD STEPPER=marco FIELD=sgt VALUE=9' in sal, repr(sal))
sal = cmds(render('MARCO_HOME', printer_falso(VARS_OFF), params={'SGT': '3'}))
check('MARCO_HOME acepta SGT= para bisectar en caliente',
      'SET_TMC_FIELD STEPPER=marco FIELD=sgt VALUE=3' in sal, repr(sal))
# _cycle_loop es un delayed_gcode, no una macro: se lee del archivo a mano.
cp = configparser.RawConfigParser(strict=False, inline_comment_prefixes=(';', '#'))
cp.read(os.path.join(CFG, 'macros_ciclo.cfg'), encoding='utf-8')
pf = printer_falso(VARS_OFF)
pf['gcode_macro _CYCLE_STATE']['stop_req'] = 1
sal = cmds(env.from_string(cp.get('delayed_gcode _cycle_loop', 'gcode')).render(dict(BASE_CTX, printer=pf)))
i_run = next((i for i, c in enumerate(sal) if 'VARIABLE=running VALUE=0' in c), None)
i_sub = next((i for i, c in enumerate(sal) if c == '_SQUEEGEE_A_ARRIBA'), None)
check('_cycle_loop cierra running=0 ANTES de subir el squeegee',
      i_run is not None and i_sub is not None and i_run < i_sub, repr(sal))

print('\n=== %d comprobaciones, %d fallos ===' % (total[0], len(fallos)))
for f in fallos:
    print('  FALLA: ' + f)
sys.exit(1 if fallos else 0)
