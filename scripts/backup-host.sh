#!/bin/sh
# Ajaa varmuuskopion Docker-kontissa. Crontabiin (esim. joka yö kello 03:30):
#
#   30 3 * * * /home/pi/docker/BuildKirjapaivakirja/scripts/backup-host.sh >> /home/pi/docker/BuildKirjapaivakirja/data/backup.log 2>&1
#
# Varmuuskopiot tallentuvat hakemistoon data/backups. Kopioi ne myös toiselle
# koneelle tai levylle (rsync/rclone), sillä sama SD-kortti ei suojaa kortin rikkoutumiselta.
set -eu
cd "$(dirname "$0")/.."
date '+%Y-%m-%d %H:%M:%S'
docker compose exec -T kirjapaivakirja python scripts/backup.py backup
