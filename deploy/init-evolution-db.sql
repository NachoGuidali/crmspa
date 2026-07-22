-- Crea la base que usa Evolution API, separada de la del CRM.
-- Postgres corre este script SOLO en el primer arranque (cuando el volumen de datos
-- está vacío). Si el volumen ya existía, creá la base a mano una vez:
--   docker compose exec db psql -U crmspa -d crmspa -c "CREATE DATABASE evolution_api OWNER crmspa;"
-- El dueño es el POSTGRES_USER que corre este init (crmspa por defecto).
CREATE DATABASE evolution_api;
