#pragma once
// =============================================================================
//  config.h  -  Parametros y mapeo del secuenciador
// =============================================================================
//  Ejes de la maquina (OJO, es facil confundirse):
//    Y = STROKE   (recorrido largo del carro; topes por stall con G38.2 Y+-500)
//    X = SQUEEGEE (subir/bajar; X-90 = subir, X+90 = bajar)
// =============================================================================

// ---------- Puertos serie ----------
// En Teensy 4.1: Serial (USB) = consola de depuracion / pruebas.
//                Serial1 (pin1=TX, pin0=RX) = enlace G-code al Octopus (USART3).
#define DBG        Serial        // consola USB para probar/loguear
#define GCODE_PORT Serial1       // enlace al Octopus (Marlin SERIAL_PORT_2 = 3)

#define GCODE_BAUD   115200      // debe coincidir con BAUDRATE_2 en Marlin
#define DBG_BAUD     115200

// ---------- Tiempos limite del handshake con Marlin ----------
// Marlin responde "ok" tras cada linea. Un movimiento largo puede tardar; mientras
// se mueve puede mandar "busy: processing" que REINICIA el contador de timeout.
#define OK_TIMEOUT_MS       20000UL   // espera normal de "ok" por linea
#define HOMING_TIMEOUT_MS   60000UL   // el G28 puede tardar mas
#define GCODE_LINE_MAXLEN   96

// ---------- Homing ----------
// El eje Y (stroke) ya esta validado. El eje X (squeegee) NUNCA se re-homeaba:
// es deuda tecnica (deriva de presion en corridas largas). Se activa aqui SOLO
// cuando confirmes que homear X no estrella el squeegee.
#define HOME_Y_ON_START   1
#define HOME_X_ON_START   0   // <-- poner 1 tras verificar que es seguro

// ---------- Receta (parametros por trabajo) ----------
// Valores por defecto = el ciclo validado en la SD (todo a F7000).
struct Recipe {
  uint16_t stroke_feed;     // F del stroke (G38.2 Y)   [mm/min]
  uint16_t squeegee_feed;   // F del squeegee (G1 X)     [mm/min]
  uint16_t stall_sens_y;    // valor de M914 Y
  // (crecera: longitudes, retardos, presion, etc.)
};

static const Recipe RECIPE_DEFAULT = {
  /* stroke_feed   */ 7000,
  /* squeegee_feed */ 7000,
  /* stall_sens_y  */ 2,
};

// ---------- Persistencia del contador ----------
// En el prototipo usamos la EEPROM emulada del Teensy. Para no desgastarla,
// NO guardamos en cada ciclo: solo cada N ciclos y al parar/pausar.
// En produccion -> FRAM I2C (FM24CL16B).
#define COUNTER_EEPROM_ADDR   0
#define COUNTER_SAVE_EVERY    100

// ---------- Mapa de registros Modbus (PROVISIONAL) ----------
// El HMI Wecon sera el MAESTRO Modbus y sondea estos holding registers.
// PENDIENTE: confirmar contra la config del puerto RS422 en PIStudio.
enum : uint16_t {
  HR_CMD          = 0,   // escribe HMI: 0=nada 1=start 2=stop 3=pause 4=resume 5=home 6=reset-fault
  HR_RECIPE       = 1,   // escribe HMI: indice de receta activa
  HR_STROKE_FEED  = 2,   // escribe HMI: override F stroke
  HR_SQUEEGEE_FEED= 3,   // escribe HMI: override F squeegee
  HR_STATE        = 10,  // lee HMI: estado actual (enum State)
  HR_CYCLES_LO    = 11,  // lee HMI: contador de ciclos (word bajo)
  HR_CYCLES_HI    = 12,  // lee HMI: contador de ciclos (word alto)
  HR_FAULT        = 13,  // lee HMI: codigo de falla
};
