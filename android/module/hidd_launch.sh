#!/system/bin/sh
export PATH=/system/bin:/system/xbin:/sbin:/vendor/bin:$PATH
MODDIR=${0%/*}
LOG=/data/adb/s20_hid.log

if pgrep -f 'nc -L -p 471[1]' >/dev/null 2>&1; then
  exit 0
fi

echo "[hidd $(date +%H:%M:%S)] listener start" >> "$LOG"
while true; do
  nc -L -p 4711 /system/bin/sh "$MODDIR/hidd.sh"
  sleep 1
done
