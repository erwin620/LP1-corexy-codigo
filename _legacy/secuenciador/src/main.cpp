// =============================================================================
//  Secuenciador de maquina serigrafica  -  esqueleto (Fase 1)
// =============================================================================
//  Objetivo de esta primera pieza: validar el PUENTE G-code con el Octopus.
//  Se maneja por la consola USB del Teensy (sin HMI ni Modbus todavia):
//     s = start    x = stop    p = pause    r = resume    h = home    ? = estado
//
//  Arquitectura (cooperativa, un solo loop, portable a ESP32/STM32):
//     loop() -> gcode.pump()  (avanza el envio y lee "ok", NO bloquea)
//            -> seq.tick()    (maquina de estados del ciclo)
//            -> console()     (comandos de prueba por USB)
//     Nada bloquea, para que en el futuro el Modbus siga respondiendo al HMI
//     incluso durante un movimiento largo.
// =============================================================================
#include <Arduino.h>
#include <EEPROM.h>
#include "config.h"

// ------------------------------------------------------------------ Estados
enum State : uint16_t { ST_IDLE, ST_HOMING, ST_RUNNING, ST_PAUSED, ST_FAULT };
static const char* stateName(State s) {
  switch (s) { case ST_IDLE:return"IDLE"; case ST_HOMING:return"HOMING";
    case ST_RUNNING:return"RUNNING"; case ST_PAUSED:return"PAUSED";
    case ST_FAULT:return"FAULT"; } return "?";
}

// ======================================================================
//  GcodeBridge  -  envia una linea, espera "ok" (no bloqueante)
// ======================================================================
class GcodeBridge {
public:
  void begin() { GCODE_PORT.begin(GCODE_BAUD); }

  bool busy()  const { return waiting_; }
  bool fault() const { return fault_; }

  // Encola una linea para enviar. Devuelve false si ya hay una en curso.
  bool send(const char* line, uint32_t timeout = OK_TIMEOUT_MS) {
    if (waiting_) return false;
    GCODE_PORT.print(line);
    GCODE_PORT.print('\n');
    DBG.print(">> "); DBG.println(line);
    waiting_ = true; timeout_ = timeout; t0_ = millis(); rxlen_ = 0;
    return true;
  }

  // Debe llamarse seguido. Lee la respuesta de Marlin y libera al ver "ok".
  void pump() {
    if (!waiting_) return;

    while (GCODE_PORT.available()) {
      char c = (char)GCODE_PORT.read();
      if (c == '\n' || c == '\r') {
        if (rxlen_ > 0) { rx_[rxlen_] = 0; handleLine(rx_); rxlen_ = 0; }
      } else if (rxlen_ < (int)sizeof(rx_) - 1) {
        rx_[rxlen_++] = c;
      }
    }

    if (waiting_ && (millis() - t0_ > timeout_)) {
      DBG.println("!! TIMEOUT esperando 'ok' de Marlin");
      fault_ = true; waiting_ = false;
    }
  }

  void clearFault() { fault_ = false; }

private:
  void handleLine(const char* s) {
    // "busy" -> Marlin sigue vivo trabajando: reinicia el timeout.
    if (strstr(s, "busy")) { t0_ = millis(); return; }
    // Errores de Marlin.
    if (s[0] == '!' || strstr(s, "Error")) {
      DBG.print("!! Marlin error: "); DBG.println(s);
      fault_ = true; waiting_ = false; return;
    }
    // Fin de comando.
    if (strncmp(s, "ok", 2) == 0) { waiting_ = false; return; }
    // Cualquier otra cosa (temperaturas, echo...) se ignora aqui.
  }

  bool     waiting_ = false;
  bool     fault_   = false;
  uint32_t t0_ = 0, timeout_ = OK_TIMEOUT_MS;
  char     rx_[128];
  int      rxlen_ = 0;
};

// ======================================================================
//  Sequencer  -  maquina de estados del ciclo serigrafico
// ======================================================================
class Sequencer {
public:
  void begin(GcodeBridge* g) {
    gc_ = g;
    recipe_ = RECIPE_DEFAULT;
    EEPROM.get(COUNTER_EEPROM_ADDR, cycles_);
    if (cycles_ == 0xFFFFFFFFUL) cycles_ = 0;   // EEPROM virgen
    state_ = ST_IDLE;
  }

  State    state()  const { return state_; }
  uint32_t cycles() const { return cycles_; }

  void start()  { if (state_ == ST_IDLE)   { step_ = 0; state_ = ST_HOMING; } }
  void stop()   { stopReq_ = true; }
  void pause()  { if (state_ == ST_RUNNING) pauseReq_ = true; }
  void resume() { if (state_ == ST_PAUSED)  { state_ = ST_RUNNING; } }
  void home()   { if (state_ == ST_IDLE)    { step_ = 0; state_ = ST_HOMING; runAfterHome_ = false; } }

  void setRecipe(const Recipe& r) { recipe_ = r; }

  void tick() {
    // Falla del puente => a FAULT.
    if (gc_->fault() && state_ != ST_FAULT) {
      state_ = ST_FAULT; saveCounter(); return;
    }
    if (gc_->busy()) return;              // esperando "ok": no avanzar

    switch (state_) {
      case ST_HOMING:  tickHoming();  break;
      case ST_RUNNING: tickRunning(); break;
      case ST_PAUSED:  /* nada */     break;
      case ST_FAULT:   /* requiere reset-fault */ break;
      case ST_IDLE:    /* nada */     break;
    }
  }

  void resetFault() {
    if (state_ == ST_FAULT) { gc_->clearFault(); state_ = ST_IDLE; }
  }

private:
  // ---- Secuencia de HOMING ----
  void tickHoming() {
    char buf[GCODE_LINE_MAXLEN];
    switch (step_) {
      case 0: gc_->send("M17"); step_++; break;                 // motores ON
      case 1: snprintf(buf,sizeof(buf),"M914 Y%u",recipe_.stall_sens_y);
              gc_->send(buf); step_++; break;                   // sensibilidad stall
    #if HOME_X_ON_START
      case 2: gc_->send("G28 X", HOMING_TIMEOUT_MS); step_++; break;
    #else
      case 2: step_++; break;
    #endif
    #if HOME_Y_ON_START
      case 3: gc_->send("G28 Y", HOMING_TIMEOUT_MS); step_++; break;
    #else
      case 3: step_++; break;
    #endif
      case 4: gc_->send("G91"); step_++; break;                 // modo relativo
      default:
        step_ = 0;
        state_ = runAfterHome_ ? ST_RUNNING : ST_IDLE;
        runAfterHome_ = true;   // por defecto start() encadena a RUNNING
        break;
    }
  }

  // ---- Un ciclo de impresion (se repite) ----
  void tickRunning() {
    char buf[GCODE_LINE_MAXLEN];
    switch (step_) {
      case 0: snprintf(buf,sizeof(buf),"G1 X-90 F%u",recipe_.squeegee_feed);
              gc_->send(buf); step_++; break;                   // sube squeegee
      case 1: snprintf(buf,sizeof(buf),"G38.2 Y500 F%u",recipe_.stroke_feed);
              gc_->send(buf); step_++; break;                   // stroke ida
      case 2: snprintf(buf,sizeof(buf),"G1 X90 F%u",recipe_.squeegee_feed);
              gc_->send(buf); step_++; break;                   // baja squeegee
      case 3: snprintf(buf,sizeof(buf),"G38.2 Y-500 F%u",recipe_.stroke_feed);
              gc_->send(buf); step_++; break;                   // stroke vuelta (imprime)
      default:
        step_ = 0;
        cycles_++;
        if (cycles_ % COUNTER_SAVE_EVERY == 0) saveCounter();
        // Parar / pausar solo entre ciclos completos (posicion consistente).
        if (stopReq_)  { stopReq_ = false; saveCounter(); state_ = ST_IDLE; }
        else if (pauseReq_) { pauseReq_ = false; saveCounter(); state_ = ST_PAUSED; }
        break;
    }
  }

  void saveCounter() { EEPROM.put(COUNTER_EEPROM_ADDR, cycles_); }

  GcodeBridge* gc_ = nullptr;
  Recipe   recipe_{};
  State    state_ = ST_IDLE;
  int      step_ = 0;
  uint32_t cycles_ = 0;
  bool     stopReq_ = false, pauseReq_ = false, runAfterHome_ = true;
};

// ======================================================================
//  Instancias globales + consola de prueba
// ======================================================================
GcodeBridge gcode;
Sequencer   seq;

static void printStatus() {
  DBG.print("estado="); DBG.print(stateName(seq.state()));
  DBG.print("  ciclos="); DBG.print(seq.cycles());
  DBG.print("  puente="); DBG.println(gcode.fault() ? "FALLA" : "ok");
}

static void console() {
  if (!DBG.available()) return;
  char c = (char)DBG.read();
  switch (c) {
    case 's': DBG.println("[start]");  seq.start();      break;
    case 'x': DBG.println("[stop]");   seq.stop();       break;
    case 'p': DBG.println("[pause]");  seq.pause();      break;
    case 'r': DBG.println("[resume]"); seq.resume();     break;
    case 'h': DBG.println("[home]");   seq.home();       break;
    case 'f': DBG.println("[reset-fault]"); seq.resetFault(); break;
    case '?': printStatus(); break;
    default: break;
  }
}

void setup() {
  DBG.begin(DBG_BAUD);
  uint32_t t = millis();
  while (!DBG && millis() - t < 2000) { /* espera USB hasta 2s */ }
  gcode.begin();
  seq.begin(&gcode);
  DBG.println("== Secuenciador serigrafico (Fase 1: puente G-code) ==");
  DBG.println("Comandos:  s=start  x=stop  p=pause  r=resume  h=home  f=reset-fault  ?=estado");
  printStatus();
}

void loop() {
  gcode.pump();   // lee "ok"/"busy" del Octopus (no bloquea)
  seq.tick();     // avanza el ciclo
  console();      // comandos de prueba por USB
  // TODO Fase 2: modbus.poll();  // atender al HMI Wecon (siempre responsivo)
}
