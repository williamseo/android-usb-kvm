#!/system/bin/sh
KBD=/dev/hidg0
TMP=/data/local/tmp/hidrep.bin
REL=/data/local/tmp/hidrel.bin

printf '\x00\x00\x00\x00\x00\x00\x00\x00' > $REL

send() {
  printf "\x$1\x00\x$2\x00\x00\x00\x00\x00" > $TMP
  cat $TMP > $KBD
  sleep 0.012
}

while IFS= read -r line; do
  set -- $line
  case "$1" in
    K)
      send "${2:-00}" "${3:-00}"
      cat $REL > $KBD
      sleep 0.012
      echo OK
      ;;
    KD)
      send "${2:-00}" "${3:-00}"
      echo OK
      ;;
    KU)
      cat $REL > $KBD
      sleep 0.012
      echo OK
      ;;
    R)
      if [ -n "$2" ]; then
        printf "$(echo "$2" | sed 's/../\\x&/g')" > $TMP
        cat $TMP > $KBD
        sleep 0.012
        echo OK
      else
        echo ERR
      fi
      ;;
    PING)
      echo PONG
      ;;
    *)
      echo ERR
      ;;
  esac
done
