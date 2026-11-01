#!/usr/bin/env bash
# Copy a whole Supabase database (roles, schema, data incl. auth users) from the OLD project to a NEW, empty project.
# The old project is only read, never changed.
set -euo pipefail

command -v supabase >/dev/null || { echo "Install the Supabase CLI first:  brew install supabase/tap/supabase"; exit 1; }
command -v psql >/dev/null     || { echo "Install psql first:  brew install libpq && brew link --force libpq"; exit 1; }
docker info >/dev/null 2>&1    || { echo "Open Docker Desktop first (supabase db dump needs it)."; exit 1; }

echo "Paste the OLD project's connection string (Dashboard > Connect > Session pooler, password filled in). Input is hidden:"
read -rs OLD_DB_URL; echo
echo "Paste the NEW project's connection string (same place, new project). Input is hidden:"
read -rs NEW_DB_URL; echo
[ "$OLD_DB_URL" != "$NEW_DB_URL" ] || { echo "Old and new strings are identical. Stopping."; exit 1; }

# Safety: only restore into an empty project
n=$(psql "$NEW_DB_URL" -At -c "select count(*) from information_schema.tables where table_schema='public'")
if [ "$n" != "0" ]; then echo "The NEW project already has $n tables in 'public'. Use a fresh, empty project. Stopping."; exit 1; fi

OUT="$HOME/supabase-migration-$(date +%Y%m%d-%H%M%S)"; mkdir -p "$OUT"; cd "$OUT"
echo "1/3 Dumping the old project into $OUT ..."
supabase db dump --db-url "$OLD_DB_URL" -f roles.sql --role-only
supabase db dump --db-url "$OLD_DB_URL" -f schema.sql
supabase db dump --db-url "$OLD_DB_URL" -f data.sql --use-copy --data-only

# Drop statements about the reserved "supabase_*" roles: they are already
# present in every Supabase project and can only be managed by a
# superuser, while the pooler connection user is not one.
grep -v 'supabase_' roles.sql > roles.filtered.sql
mv roles.filtered.sql roles.sql

read -rp "2/3 Restore into the NEW project now? Type YES to continue: " ok
[ "$ok" = "YES" ] || { echo "Stopped. Dump files are in $OUT"; exit 1; }

# Apply the schema first: afterwards the current user can be granted the
# privileges the data load needs (some tables are owned by reserved
# Supabase roles).
psql --single-transaction --variable ON_ERROR_STOP=1 \
  --command 'SET session_replication_role = replica' \
  --file roles.sql --file schema.sql --dbname "$NEW_DB_URL"

psql "$NEW_DB_URL" -v ON_ERROR_STOP=1 <<'SQL'
DO $$
DECLARE r record;
BEGIN
  FOR r IN
    SELECT table_schema, table_name FROM information_schema.tables
    WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
  LOOP
    EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON %I.%I TO %I', r.table_schema, r.table_name, current_user);
  END LOOP;
END $$;
SQL

# Skip the COPY blocks for tables owned by reserved Supabase roles: the
# pooler connection user cannot write to them.
psql "$NEW_DB_URL" -At -c "select schema||'.'||table_name from pg_class c join pg_namespace n on n.oid = c.relnamespace join pg_roles r on r.oid = c.relowner where c.relkind in ('r','p') and r.rolname like 'supabase\_%' escape '\'" > reserved_tables.txt
awk '
BEGIN {
  while ((getline line < "reserved_tables.txt") > 0) {
    split(line, parts, ".")
    for (i = 1; i <= 2; i++) {
      t = parts[i]
      gsub(/"/, "", t)
      if (t != "") reserved[t] = 1
    }
    close(line)
  }
}
{
  if (skip) {
    if ($0 == "\\.") skip = 0
    next
  }
  if ($0 ~ /^COPY[ ]/) {
    s = $0
    sub(/^COPY[ ]+/, "", s)
    ok = 1
    for (pass = 1; pass <= 2; pass++) {
      if (match(s, /"[^"]+"/)) {
        tok = substr(s, RSTART + 1, RLENGTH - 2)
        gsub(/"/, "", tok)
        if (tok in reserved) { skip = 1; break }
        s = substr(s, RSTART + RLENGTH)
      } else { ok = 0; break }
    }
    if (skip) next
  }
  print
}
' data.sql > data.filtered.sql
mv data.filtered.sql data.sql

psql --single-transaction --variable ON_ERROR_STOP=1 \
  --file data.sql --dbname "$NEW_DB_URL"

echo "3/3 Comparing exact row counts (public + auth tables)..."
count() {
  psql "$1" -At -c "select format('select %L || '' '' || count(*) from %I.%I;', table_schema||'.'||table_name, table_schema, table_name)
                    from information_schema.tables
                    where table_schema in ('public','auth') and table_type='BASE TABLE' order by 1" | psql "$1" -At
}
count "$OLD_DB_URL" > old_counts.txt
count "$NEW_DB_URL" > new_counts.txt
if diff old_counts.txt new_counts.txt; then echo "Done: every table has the same number of rows in both projects."
else echo "Some counts differ (shown above). Don't switch the app over yet."; fi
echo "Dump files (contain real user and contract data) are in $OUT — delete them once you're happy."
