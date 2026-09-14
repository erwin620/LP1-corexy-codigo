#!/bin/bash
PROFILE="/home/aspe/.config/kiosk-chromium"
PREF="$PROFILE/Default/Preferences"
SPLASH="/usr/share/plymouth/themes/serigrafia/splash.png"
mkdir -p "$PROFILE"
if [ -f "$PREF" ]; then
  sed -i 's/"exited_cleanly":false/"exited_cleanly":true/; s/"exit_type":"[^"]*"/"exit_type":"Normal"/' "$PREF"
fi

# ---------------------------------------------------------------------------
# SPLASH MIENTRAS ARRANCA CHROMIUM  (feature 008, 2026-08-19)
# ---------------------------------------------------------------------------
# MEDIDO en el journal: cage abre sesion a los 14.06 s y Chromium no mapea su
# ventana hasta los 18.68 s. En esos ~4.6 s cage pinta NEGRO, y era el unico
# negro que seguia viendose (Erwin: "el negro es antes de la interfaz").
#
# imv-wayland muestra LA MISMA imagen que plymouth como ventana normal. Cuando
# Chromium mapea, cage lo dibuja encima y el relevo no se nota.
#
# swaybg NO SIRVE, aunque parezca la herramienta obvia: necesita el protocolo
# wlr-layer-shell y cage NO lo implementa. Probado contra la sesion viva:
#   "Missing a required Wayland interface"
#
# OJO CON EL NOMBRE DEL BINARIO: el paquete se llama 'imv' pero el ejecutable es
# 'imv-wayland' (tambien trae imv-x11). Llamar a 'imv' da "No such file".
#
# No se intenta matarlo "cuando Chromium pinte" porque no hay forma fiable de
# detectarlo desde aqui; se mata por tiempo, cuando ya lleva mucho tapado.
# ---------------------------------------------------------------------------
if [ -r "$SPLASH" ] && command -v imv-wayland >/dev/null 2>&1; then
  imv-wayland -f -b "#000000" -s full "$SPLASH" &
  IMV_PID=$!
  ( sleep 40; kill "$IMV_PID" 2>/dev/null ) &
fi

exec /usr/bin/chromium \
  --kiosk \
  --app=http://localhost/serigrafia/ \
  --user-data-dir="$PROFILE" \
  --ozone-platform=wayland \
  --noerrdialogs \
  --disable-infobars \
  --disable-session-crashed-bubble \
  --disable-features=Translate,TranslateUI \
  --no-first-run \
  --fast --fast-start \
  --disable-pinch \
  --overscroll-history-navigation=0 \
  --disable-component-update \
  --check-for-update-interval=604800 \
  --password-store=basic \
  --disable-notifications \
  --hide-scrollbars
