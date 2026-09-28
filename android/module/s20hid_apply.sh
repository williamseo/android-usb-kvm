#!/system/bin/sh
export PATH=/system/bin:/system/xbin:/sbin:/vendor/bin:$PATH
MODDIR=${0%/*}
MODE=${1:-apply}
G=/config/usb_gadget/g1
LOG=/data/adb/s20_hid.log

log() { echo "[apply $(date +%H:%M:%S)] $*" >> "$LOG"; }

applied() {
  [ -c /dev/hidg0 ] || return 1
  [ -n "$(cat $G/UDC 2>/dev/null)" ] || return 1
  [ "$(readlink -f $G/configs/b.1/f1 2>/dev/null)" = "$G/functions/hid.usb0" ] || return 1
  return 0
}

if [ "$MODE" = "watchdog" ] && applied; then
  exit 0
fi

U=$(getprop sys.usb.controller)
[ -z "$U" ] && U=a600000.dwc3
log "applying ($MODE) udc=$U"

setprop service.adb.tcp.port 5555
setprop sys.usb.config none
sleep 2

for f in f1 f2 f3 f4 f5 f6 f7 f8 f9; do
  rm -f "$G/configs/b.1/$f"
done

if [ ! -d "$G/functions/hid.usb0" ]; then
  mkdir "$G/functions/hid.usb0"
fi

echo 1 > "$G/functions/hid.usb0/protocol"
echo 1 > "$G/functions/hid.usb0/subclass"
echo 8 > "$G/functions/hid.usb0/report_length"
cat "$MODDIR/hid_desc_kbd.bin" > "$G/functions/hid.usb0/report_desc"
chmod 666 "$G/functions/hid.usb0/report_desc"

ln -s "$G/functions/hid.usb0" "$G/configs/b.1/f1"
echo "$U" > "$G/UDC"
sleep 1

start adbd 2>/dev/null
log "done udc=[$(cat $G/UDC)] hidg=[$(ls /dev/hidg* 2>/dev/null)]"
