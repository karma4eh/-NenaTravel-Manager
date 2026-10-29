# Directorio de Respaldos de Base de Datos • Viajes Nena

En esta carpeta se almacenan las copias de seguridad de la base de datos SQLite (`db.sqlite3`).

### Historial de Respaldos:
- `db.sqlite3.backup_before_reset`: Respaldo previo a la primera limpieza para la demostración beta.
- `db.sqlite3.backup_before_online_reset`: Respaldo previo a la puesta en línea con Cloudflare Tunnel.

### Cómo restaurar un respaldo:
Para volver a un estado anterior:
1. Detén el servidor Django.
2. Copia el archivo deseado a la raíz reemplazando `db.sqlite3`:
   ```powershell
   Copy-Item "backups/db.sqlite3.backup_before_reset" -Destination "db.sqlite3" -Force
   ```
3. Reinicia el servidor Django.
