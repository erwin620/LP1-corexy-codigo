#pragma once
// Parámetros y mapeo del secuenciador.
//
// Ejes de la máquina:
//   Y = stroke   (recorrido largo del carro; topes por stall con G38.2 Y+-500)
//   X = squeegee (X-90 = subir, X+90 = bajar)

// Puertos serie (Teensy 4.1).
#define DBG        Serial        // USB: consola de depuración y pruebas
#define GCODE_PORT Serial1       // pin1=TX, pin0=RX: G-code al Octopus (Marlin SERIAL_PORT_2 = 3, USART3)

#define GCODE_BAUD   115200      // debe coincidir con BAUDRATE_2 en Marlin
#define DBG_BAUD     115200

// Marlin responde "ok" tras cada línea. Durante un movimiento largo envía
// "busy: processing", que reinicia el contador de timeout.
#define OK_TIMEOUT_MS       20000UL
#define HOMING_TIMEOUT_MS   60000UL   // el G28 puede tardar más
#define GCODE_LINE_MAXLEN   96

// El homing de X (squeegee) está desactivado hasta verificar que no golpea la
// malla. Sin él, la presión puede derivar en corridas largas.
#define HOME_Y_ON_START   1
#define HOME_X_ON_START   0

// Receta por trabajo. Los valores por defecto corresponden al ciclo validado
// (todo a F7000).
struct Recipe {
  uint16_t stroke_feed;     // F del stroke (G38.2 Y)   [mm/min]
  uint16_t squeegee_feed;   // F del squeegee (G1 X)     [mm/min]
  uint16_t stall_sens_y;    // valor de M914 Y
};

static const Recipe RECIPE_DEFAULT = {
  /* stroke_feed   */ 7000,
  /* squeegee_feed */ 7000,
  /* stall_sens_y  */ 2,
};

// El contador de ciclos se guarda en la EEPROM emulada del Teensy solo cada
// N ciclos y al parar o pausar, para no desgastarla. En producción se
// preveía una FRAM I2C (FM24CL16B).
#define COUNTER_EEPROM_ADDR   0
#define COUNTER_SAVE_EVERY    100

// Holding registers Modbus que sondea el HMI Wecon (maestro). Mapa provisional,
// sin confirmar contra la configuración del puerto RS422 en PIStudio.
enum : uint16_t {
  HR_CMD          = 0,   // escribe HMI: 0=nada 1=start 2=stop 3=pause 4=resume 5=home 6=reset-fault
  HR_RECIPE       = 1,   // escribe HMI: índice de receta activa
  HR_STROKE_FEED  = 2,   // escribe HMI: override F stroke
  HR_SQUEEGEE_FEED= 3,   // escribe HMI: override F squeegee
  HR_STATE        = 10,  // lee HMI: estado actual (enum State)
  HR_CYCLES_LO    = 11,  // lee HMI: contador de ciclos (word bajo)
  HR_CYCLES_HI    = 12,  // lee HMI: contador de ciclos (word alto)
  HR_FAULT        = 13,  // lee HMI: código de falla
};
