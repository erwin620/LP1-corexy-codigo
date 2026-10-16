// Secuenciador de máquina serigráfica: envía el ciclo de impresión como G-code
// a Marlin (placa Octopus) y espera el "ok" de cada línea.
//
// Esta versión se maneja por la consola USB del Teensy, sin HMI ni Modbus:
//    s = start  x = stop  p = pause  r = resume  h = home  f = reset-fault  ? = estado
//
// Multitarea cooperativa en un solo loop(), portable a ESP32/STM32. Ninguna
// tarea bloquea, para que el esclavo Modbus pueda seguir respondiendo al HMI
// durante un movimiento largo.
#include <Arduino.h>
#include <EEPROM.h>
#include "config.h"

enum State : uint16_t { ST_IDLE, ST_HOMING, ST_RUNNING, ST_PAUSED, ST_FAULT };
static const char* stateName(State s) {
  switch (s) { case ST_IDLE:return"IDLE"; case ST_HOMING:return"HOMING";
    case ST_RUNNING:return"RUNNING"; case ST_PAUSED:return"PAUSED";
    case ST_FAULT:return"FAULT"; } return "?";
}

// Envía una línea de G-code y espera el "ok" sin bloquear.
class GcodeBridge {
public:
  void begin() { GCODE_PORT.begin(GCODE_BAUD); }

  bool busy()  const { return waiting_; }
  bool fault() const { return fault_; }

  // Devuelve false si todavía hay una línea esperando su "ok".
  bool send(const char* line, uint32_t timeout = OK_TIMEOUT_MS) {
    if (waiting_) return false;
    GCODE_PORT.print(line);
    GCODE_PORT.print('\n');
    DBG.print(">> "); DBG.println(line);
    waiting_ = true; timeout_ = timeout; t0_ = millis(); rxlen_ = 0;
    return true;
  }

  // Debe llamarse en cada vuelta de loop(): lee la respuesta de Marlin y
  // detecta el timeout.
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
    // "busy": Marlin sigue ejecutando el comando; se reinicia el timeout.
    if (strstr(s, "busy")) { t0_ = millis(); return; }
    if (s[0] == '!' || strstr(s, "Error")) {
      DBG.print("!! Marlin error: "); DBG.println(s);
      fault_ = true; waiting_ = false; return;
    }
    if (strncmp(s, "ok", 2) == 0) { waiting_ = false; return; }
    // El resto (temperaturas, echo...) se ignora.
  }

  bool     waiting_ = false;
  bool     fault_   = false;
  uint32_t t0_ = 0, timeout_ = OK_TIMEOUT_MS;
  char     rx_[128];
  int      rxlen_ = 0;
};

// Máquina de estados del ciclo serigráfico.
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
    if (gc_->fault() && state_ != ST_FAULT) {
      state_ = ST_FAULT; saveCounter(); return;
    }
    if (gc_->busy()) return;

    switch (state_) {
      case ST_HOMING:  tickHoming();  break;
      case ST_RUNNING: tickRunning(); break;
      case ST_PAUSED:                 break;
      case ST_FAULT:   /* sale solo con resetFault() */ break;
      case ST_IDLE:                   break;
    }
  }

  void resetFault() {
    if (state_ == ST_FAULT) { gc_->clearFault(); state_ = ST_IDLE; }
  }

private:
  void tickHoming() {
    char buf[GCODE_LINE_MAXLEN];
    switch (step_) {
      case 0: gc_->send("M17"); step_++; break;                 // habilita motores
      case 1: snprintf(buf,sizeof(buf),"M914 Y%u",recipe_.stall_sens_y);
              gc_->send(buf); step_++; break;                   // sensibilidad de stall
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
        runAfterHome_ = true;   // home() lo apaga para una sola orden; start() encadena el ciclo
        break;
    }
  }

  // Un ciclo de impresión; se repite hasta stop o pause.
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
        // Parar o pausar solo entre ciclos completos, con la posición conocida.
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
  while (!DBG && millis() - t < 2000) { /* espera la consola USB hasta 2 s */ }
  gcode.begin();
  seq.begin(&gcode);
  DBG.println("== Secuenciador serigrafico (Fase 1: puente G-code) ==");
  DBG.println("Comandos:  s=start  x=stop  p=pause  r=resume  h=home  f=reset-fault  ?=estado");
  printStatus();
}

void loop() {
  gcode.pump();
  seq.tick();
  console();
}
