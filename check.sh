#!/usr/bin/env bash
# Sends 20 requests and reports how many succeeded, like an SLO check.
URL="${1:-http://localhost:8080}"
ok=0
for i in $(seq 1 20); do
  code=$(curl -s -o /dev/null -w "%{http_code}" "$URL/")
  [ "$code" = "200" ] && ok=$((ok + 1))
done
echo "$ok/20 requests succeeded ($((ok * 5))%) at $URL"
[ "$ok" -ge 19 ] && echo "SLO met (95% or more)" || echo "SLO BROKEN: page someone!"
