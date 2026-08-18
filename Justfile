# GPURent — Justfile
# Usage: just <command>

# Default: run Django system checks
default: check

# Run Django system checks
check:
    uv run manage.py check

# Apply pending migrations
migrate:
    uv run manage.py migrate

# Create migrations
makemigrations:
    uv run manage.py makemigrations

# Run development server
dev:
    uv run honcho start

# Run simulation worker
run_simulation:
    uv run manage.py run_simulation

# Seed GPU catalog
seed:
    uv run manage.py seed_catalog

# Run tests (defaults to all tests, or pass specific apps/options)
test *args="-v 0":
    uv run manage.py test {{args}} --force-color

# Run guardian audit
guardian_audit:
    uv run manage.py guardian_audit

# Django shell
shell:
    uv run manage.py shell

# Show URLs
show_urls:
    uv run manage.py show_urls

upgrade package:
    @echo "Upgrade {{ package }} ..."
    uv sync --upgrade-package {{ package }}
