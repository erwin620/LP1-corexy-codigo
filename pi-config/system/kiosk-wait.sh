#!/bin/bash
# Espera a que respondan la interfaz (nginx) y la API de Moonraker antes de
# lanzar el kiosco: si Chromium abre antes, muestra una página de error.
# Termina siempre con 0 para que el kiosco arranque aunque se agote el plazo.
UI="http://localhost/serigrafia/"
MK="http://localhost:7125/server/info"
end=$((SECONDS+180))
while [ $SECONDS -lt $end ]; do
  c1=$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "$UI" 2>/dev/null || true)
  c2=$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "$MK" 2>/dev/null || true)
  [ "$c1" = "200" ] && [ "$c2" = "200" ] && exit 0
  sleep 2
done
exit 0