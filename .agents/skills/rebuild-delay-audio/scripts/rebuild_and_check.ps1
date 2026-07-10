$ErrorActionPreference = "Stop"

$remote = @'
set -e
cd /volume1/docker/web
sudo env BUILDX_GIT_INFO=false docker compose up -d --build delay-audio
echo "--- docker ps ---"
sudo docker ps --filter 'name=^/delay-audio$' --format '{{.Names}} {{.Status}} {{.Ports}}'
echo "--- http ---"
err_file="$(mktemp)"
ok=0
last_code=""
for attempt in $(seq 1 20); do
  last_code="$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:9004/ 2>"$err_file" || true)"
  if [ "$last_code" = "200" ]; then
    echo "HTTP 200"
    ok=1
    break
  fi
  show_code="$last_code"
  if [ -z "$show_code" ] || [ "$show_code" = "000" ]; then
    show_code="sin-respuesta"
  fi
  if [ "$attempt" -lt 20 ]; then
    echo "HTTP esperando ${attempt}/20: $show_code"
    sleep 2
  fi
done
if [ "$ok" -ne 1 ]; then
  show_code="$last_code"
  if [ -z "$show_code" ] || [ "$show_code" = "000" ]; then
    show_code="sin-respuesta"
  fi
  echo "HTTP fallo tras reintentos: $show_code"
  if [ -s "$err_file" ]; then
    cat "$err_file"
  fi
  rm -f "$err_file"
  exit 1
fi
rm -f "$err_file"
'@

$remote = $remote -replace "`r", ""

Write-Host "Validando sintaxis remota..."
$remote | ssh lacabra@192.168.1.159 bash -n

Write-Host "Ejecutando rebuild y comprobaciones..."
$remote | ssh lacabra@192.168.1.159 bash -s
