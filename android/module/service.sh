#!/system/bin/sh
export PATH=/system/bin:/system/xbin:/sbin:/vendor/bin:$PATH
MODDIR=${0%/*}
LOG=/data/adb/s20_hid.log

log() { echo "[service $(date +%H:%M:%S)] $*" >> "$LOG"; }

log "service start"
while [ "$(getprop sys.boot_completed)" != "1" ]; do
  sleep 3
done
sleep 8

setprop persist.adb.tcp.port 5555
setprop service.adb.tcp.port 5555
start adbd 2>/dev/null
log "adbd requested"

sh "$MODDIR/s20hid_apply.sh" apply

setsid sh "$MODDIR/hidd_launch.sh" >/dev/null 2>&1 &
log "hidd launcher started"

(
  while true; do
    sleep 20
    sh "$MODDIR/s20hid_apply.sh" watchdog
    if ! pgrep -x adbd >/dev/null 2>&1; then
      log "adbd down, restart"
      setprop service.adb.tcp.port 5555
      start adbd 2>/dev/null
    fi
  done
) &
