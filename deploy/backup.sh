#!/usr/bin/env bash
# Copia de seguridad diaria del CRM: las dos bases y los archivos subidos.
#
# Qué se guarda y por qué:
#   - base del CRM: reservas, contactos, pagos, conversaciones. Sin esto no hay negocio.
#   - base de Evolution: la sesión de WhatsApp. Si se pierde, hay que escanear el QR de nuevo.
#   - media: los comprobantes de transferencia (los necesita contabilidad) y las fotos.
#
# Uso:
#   sudo /opt/crmspa/deploy/backup.sh              # a /opt/crmspa/backups
#   sudo /opt/crmspa/deploy/backup.sh /otra/ruta   # a donde quieras (ej. un disco montado)
#
# Para que corra solo, todos los días a las 3 de la mañana:
#   sudo crontab -e
#   0 3 * * * /opt/crmspa/deploy/backup.sh >> /var/log/crmspa-backup.log 2>&1
set -euo pipefail

PROYECTO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DESTINO="${1:-$PROYECTO/backups}"
DIAS_A_CONSERVAR="${DIAS_A_CONSERVAR:-14}"
FECHA="$(date +%Y-%m-%d_%H%M)"

cd "$PROYECTO"
mkdir -p "$DESTINO"

# El usuario de la base sale del .env, para no repetirlo acá.
DB_USER="$(grep -E '^DB_USER=' .env 2>/dev/null | cut -d= -f2- || true)"
DB_USER="${DB_USER:-crmspa}"
DB_NAME="$(grep -E '^DB_NAME=' .env 2>/dev/null | cut -d= -f2- || true)"
DB_NAME="${DB_NAME:-crmspa}"

echo "[$(date +%H:%M:%S)] Backup en $DESTINO"

# ── Bases ──
# pg_dump corre DENTRO del contenedor: no hace falta tener postgres instalado en el host.
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" | gzip > "$DESTINO/crm_$FECHA.sql.gz"

if docker compose exec -T db psql -U "$DB_USER" -lqt | cut -d\| -f1 | grep -qw evolution_api; then
  docker compose exec -T db pg_dump -U "$DB_USER" evolution_api | gzip > "$DESTINO/evolution_$FECHA.sql.gz"
fi

# ── Archivos subidos ──
# Con el web andando se lee de ahí. Si está apagado, se lee el volumen con un contenedor
# mínimo: NO se usa `docker compose run`, porque escupe el log del build en la misma salida
# y el archivo sale corrupto (pasó).
if docker compose ps --status running --services 2>/dev/null | grep -qx web; then
  docker compose exec -T web tar czf - -C /app/media . > "$DESTINO/media_$FECHA.tar.gz" 2>/dev/null || true
else
  # El nombre del volumen lo arma compose con el nombre del proyecto (la carpeta).
  VOLUMEN="${COMPOSE_PROJECT_NAME:-$(basename "$PROYECTO")}_media_data"
  if docker volume inspect "$VOLUMEN" >/dev/null 2>&1; then
    echo "  (web apagado: leo el volumen $VOLUMEN)"
    # Se monta en /respaldo y no en /media: montar sobre una carpeta que la imagen ya tiene
    # hace que Docker copie el contenido de la imagen adentro del volumen. O sea, ensucia
    # justo lo que se quiere respaldar.
    docker run --rm -v "$VOLUMEN":/respaldo:ro alpine tar czf - -C /respaldo . > "$DESTINO/media_$FECHA.tar.gz" 2>/dev/null || true
  else
    echo "  ⚠️  no encontré el volumen $VOLUMEN"
  fi
fi

# ── Verificación: un backup que no se puede abrir es peor que no tener backup ──
PROBLEMAS=0
for f in "$DESTINO/crm_$FECHA.sql.gz" "$DESTINO/evolution_$FECHA.sql.gz" "$DESTINO/media_$FECHA.tar.gz"; do
  [ -f "$f" ] || continue
  SANO=0
  case "$f" in
    # Un dump de la base nunca es diminuto: si lo es, algo salió mal.
    *.sql.gz) gzip -t "$f" 2>/dev/null && [ "$(stat -c%s "$f")" -gt 1000 ] && SANO=1 ;;
    # El tar tiene que poder listarse. Vacío es válido: puede no haber comprobantes todavía.
    *.tar.gz) gzip -t "$f" 2>/dev/null && tar tzf "$f" >/dev/null 2>&1 && SANO=1 ;;
  esac
  if [ "$SANO" -eq 1 ]; then
    DETALLE=""
    case "$f" in *.tar.gz) DETALLE="  ($(tar tzf "$f" 2>/dev/null | wc -l) archivos)" ;; esac
    echo "  ok  $(basename "$f")  $(du -h "$f" | cut -f1)$DETALLE"
  else
    echo "  ⚠️  ROTO: $(basename "$f") — se borra"
    rm -f "$f"; PROBLEMAS=1
  fi
done

# ── Limpieza ──
find "$DESTINO" -name '*.sql.gz' -o -name '*.tar.gz' | while read -r f; do
  if [ "$(find "$f" -mtime +"$DIAS_A_CONSERVAR" | wc -l)" -gt 0 ]; then rm -f "$f"; echo "  borrado (viejo): $(basename "$f")"; fi
done

if [ "$PROBLEMAS" -ne 0 ]; then
  echo "[$(date +%H:%M:%S)] TERMINÓ CON PROBLEMAS: faltan archivos del backup."
fi
echo "[$(date +%H:%M:%S)] Listo. En $DESTINO hay $(ls -1 "$DESTINO" | wc -l) archivos."
echo
echo "Para restaurar la base del CRM (CUIDADO: pisa los datos actuales):"
echo "  gunzip -c $DESTINO/crm_$FECHA.sql.gz | docker compose exec -T db psql -U $DB_USER -d $DB_NAME"
echo "Para restaurar los archivos:"
echo "  cat $DESTINO/media_$FECHA.tar.gz | docker compose exec -T web tar xzf - -C /app/media"
exit "$PROBLEMAS"
