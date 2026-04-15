# PPC Dashboard - Advanced Setup Options

## Current Setup (Recommended) ✅

Your optimized dashboard is now:
- **Fast**: Instant load from cache
- **Fresh**: 30-second update cycle
- **Simple**: No external databases
- **Reliable**: Graceful fallback to cache

---

## Optional: If You Want MongoDB Later

### Why MongoDB?
```
Use MongoDB when you need:
✓ History > 3 months
✓ Multiple factories sharing data
✓ Advanced analytics/reports
✓ Real-time collaboration

Don't use MongoDB if:
✗ Only need today/yesterday data
✗ Single-user/single-factory
✗ Limited budget for infrastructure
```

### Quick Setup (if needed)

```bash
# 1. Install MongoDB driver
pip install pymongo

# 2. Install MongoDB Community
# Windows: https://www.mongodb.com/try/download/community
# Or use MongoDB Atlas (cloud): https://www.mongodb.com/cloud/atlas

# 3. Update ppc.py with MongoDB support
# See MONGODB_INTEGRATION.md
```

---

## Optional: Redis for Shared Cache

### When to use Redis?
```
Single Server? → No need for Redis
Multiple Servers/Workers? → Add Redis
Need instance data across processes? → Add Redis
```

### Quick Setup

```bash
# Windows
choco install redis  # or docker
redis-server  # starts locally on port 6379

# Python
pip install redis

# Then add to ppc.py:
import redis
cache = redis.Redis(host='localhost', port=6379, db=0)
```

---

## Optional: SQLite for Local History

### Lightweight & Easy

```bash
pip install sqlite3  # usually pre-installed

# Then add to ppc.py:
import sqlite3

conn = sqlite3.connect('data/ppc_history.db')
cursor = conn.cursor()
cursor.execute('''
    CREATE TABLE IF NOT EXISTS bpo_history (
        id INTEGER PRIMARY KEY,
        bpo_number TEXT,
        data JSON,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
''')
```

**Pros**: Simple, no dependencies  
**Cons**: Single-server only, slower than MongoDB

---

## Performance Tuning Reference

### Environment Variables to Set

```bash
# .env file or system environment variables

# API timeout (seconds) - Lower = faster fallback to cache
PPC_LIVE_TIMEOUT=4

# Refresh interval (milliseconds) - Lower = fresher data
PPC_LIVE_REFRESH_MS=30000

# Cache validity (seconds) - Higher = fewer API calls
PPC_LIVE_CACHE_TTL=45

# How many days back to fetch - Lower = less data
PPC_LIVE_LOOKBACK_DAYS=1

# API endpoint - Update if server changes
PPC_LIVE_ENDPOINT=http://110.38.236.7:7003/ords/ws_apparel/ppc-planner/bpo
```

### Setting Environment Variables

**Windows PowerShell**:
```powershell
$env:PPC_LIVE_TIMEOUT = "4"
$env:PPC_LIVE_REFRESH_MS = "30000"
# Then run: python ppc.py
```

**Windows Command Prompt**:
```cmd
set PPC_LIVE_TIMEOUT=4
set PPC_LIVE_REFRESH_MS=30000
python ppc.py
```

**Linux/Mac**:
```bash
export PPC_LIVE_TIMEOUT=4
export PPC_LIVE_REFRESH_MS=30000
python ppc.py
```

---

## Ultra-Fast Preloading (Advanced)

### WAL (Write-Ahead Logging) for Cache

```python
# Code to add if cache grows very large
import sqlite3

def enable_wal_mode():
    conn = sqlite3.connect('data/live_planner_cache.json')
    conn.execute('PRAGMA journal_mode=WAL')
    print("WAL mode enabled for faster cache")
```

### Compression for Cache Files

```python
import gzip
import json

def save_compressed_cache(data):
    with gzip.open('data/cache.json.gz', 'wt') as f:
        json.dump(data, f)

def load_compressed_cache():
    with gzip.open('data/cache.json.gz', 'rt') as f:
        return json.load(f)
```

---

## Troubleshooting Performance

### Symptom: Still slow

**Check 1: API Endpoint**
```bash
# Test API speed from your machine
# Open browser: http://110.38.236.7:7003/ords/ws_apparel/ppc-planner/bpo
# If page loads slow = API is slow, not your code
```

**Check 2: Network**
```bash
# Test internet speed
# If < 1 Mbps = network is bottleneck
# Solution: Reduce PPC_LIVE_LOOKBACK_DAYS to 1
```

**Check 3: CPU/Memory**
```bash
# Open Task Manager → Performance
# If CPU > 80% = data processing too heavy
# Solution: Reduce PPC_LIVE_LOOKBACK_DAYS to 1
```

### Symptom: Cache not updating

**Check**:
```
- Is interval running? Check logs for [CACHE-HIT] or [API-CALL]
- Is file writable? Check data/live_planner_cache.json
- Permissions ok? Try chmod 666 live_planner_cache.json
```

### Symptom: Using old data

**Solution**: Force refresh
```python
# Clear cache
import os
os.remove('data/live_planner_cache.json')
# App will fetch fresh data on next load
```

---

## Deployment Checklist

- [ ] Test on slow network (3G/4G)
- [ ] Test with no internet (offline mode)
- [ ] Check cache file size < 10 MB
- [ ] Monitor memory usage in production
- [ ] Set backup for saved plans
- [ ] Document custom timeout settings
- [ ] Enable debug logs for first week

---

## Questions?

See: `OPTIMIZATION_GUIDE.md` for architecture  
See: `PERFORMANCE_COMPARISON.md` for metrics  

**Ready to scale?** Contact IT for MongoDB/Redis setup.
