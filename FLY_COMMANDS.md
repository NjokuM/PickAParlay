# Fly.io Commands Reference

## Deploy

```bash
# Deploy latest code (rebuild + restart)
fly deploy -a pickaparlay

# Deploy without cache (if Docker build is stale)
fly deploy -a pickaparlay --no-cache
```

## Status & Logs

```bash
# Check if app is running
fly status -a pickaparlay

# Live logs (stream)
fly logs -a pickaparlay

# Recent logs (last 100 lines)
fly logs -a pickaparlay --no-tail
```

## Secrets (API Keys, Config)

```bash
# List current secrets (names only, not values)
fly secrets list -a pickaparlay

# Set/change a secret (auto-restarts the machine)
fly secrets set ODDS_API_KEY="your-key-here" -a pickaparlay

# Set multiple at once
fly secrets set ODDS_API_KEY="key" JWT_SECRET_KEY="secret" -a pickaparlay

# Remove a secret
fly secrets unset SOME_SECRET -a pickaparlay
```

## SSH & Database

```bash
# SSH into the running machine
fly ssh console -a pickaparlay

# If SSH fails, re-issue credentials first
fly ssh issue personal --agent
fly ssh console -a pickaparlay

# Run a quick command without interactive shell
fly ssh console -a pickaparlay -C "ls /data"

# Check database size
fly ssh console -a pickaparlay -C "du -h /data/pickaparlay.db"

# Run a SQL query
fly ssh console -a pickaparlay -C "python3 -c \"import sqlite3; c=sqlite3.connect('/data/pickaparlay.db'); print(c.execute('SELECT COUNT(*) FROM graded_props').fetchone())\""
```

## File Transfer (SFTP)

```bash
# Upload a file to the machine
fly sftp shell -a pickaparlay
# then: put local_file.db /data/pickaparlay.db

# Download a file from the machine
fly sftp shell -a pickaparlay
# then: get /data/pickaparlay.db ./backup.db
```

## Scaling & Resources

```bash
# Check current machine size
fly scale show -a pickaparlay

# Scale memory (max 2048 on shared CPU)
fly scale memory 2048 -a pickaparlay

# Restart without redeploying
fly machine restart -a pickaparlay
```

## Troubleshooting

```bash
# App won't start — check build logs
fly deploy -a pickaparlay 2>&1 | tail -50

# App crashes — check recent logs
fly logs -a pickaparlay --no-tail | grep -i "error\|killed\|oom"

# Machine stuck — force restart
fly machine restart -a pickaparlay

# Check which region/size
fly status -a pickaparlay
```
