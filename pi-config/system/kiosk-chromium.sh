#!/bin/bash
PROFILE="/home/aspe/.config/kiosk-chromium"
PREF="$PROFILE/Default/Preferences"
SPLASH="/usr/share/plymouth/themes/serigrafia/splash.png"
mkdir -p "$PROFILE"
# Tras un corte de corriente Chromium ofrecería restaurar la sesión; se marca
# el perfil como cerrado correctamente para que el kiosco arranque limpio.
if [ -f "$PREF" ]; then
  sed -i 's/"exited_cleanly":false/"exited_cleanly":true/; s/"exit_type":"[^"]*"/"exit_type":"Normal"/' "$PREF"
fi

# Pantalla de arranque mientras Chromium abre su ventana.
#
# Entre el inicio de la sesión de cage y el primer frame de Chromium pasan
# unos 4-5 s en los que cage pinta negro. imv-wayland muestra la misma imagen
# que Plymouth como ventana normal; cuando Chromium mapea, cage lo dibuja
# encima y el relevo no se nota.
#
# swaybg no sirve: requiere el protocolo wlr-layer-shell, que cage no
# implementa ("Missing a required Wayland interface").
#
# El paquete se llama 'imv', pero el ejecutable Wayland es 'imv-wayland'.
#
# No hay forma fiable de detectar desde aquí cuándo Chromium ya pintó, así que
# el visor se cierra por tiempo, con margen de sobra.
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
