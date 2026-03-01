#!/usr/bin/env python3
import sys
sys.path.insert(0, 'frontend/backend')
sys.path.insert(0, 'src')

import os
os.environ['DB_PATH'] = ':memory:'

from fastapi.testclient import TestClient
from app.api.system import router
from fastapi import FastAPI

app = FastAPI()
app.include_router(router)

client = TestClient(app)

print("Testing /api/system/health")
resp = client.get("/api/system/health")
print(f"Status: {resp.status_code}")
if resp.status_code == 200:
    data = resp.json()
    print(f"Services: {list(data.get('services', {}).keys())}")
    print(f"Sentinel status: {data.get('services', {}).get('sentinel', {})}")
else:
    print(resp.text)

print("\nTesting /api/system/quota")
resp = client.get("/api/system/quota")
print(f"Status: {resp.status_code}")
if resp.status_code == 200:
    data = resp.json()
    print(f"Month: {data.get('month')}, used_percent: {data.get('used_percent')}")

print("\nTesting /api/system/risk")
resp = client.get("/api/system/risk")
print(f"Status: {resp.status_code}")
if resp.status_code == 200:
    data = resp.json()
    print(f"Risk mode: {data.get('risk_mode')}, drawdown remaining: {data.get('drawdown_remaining_pct')}")

print("\nTesting /api/system/events")
resp = client.get("/api/system/events")
print(f"Status: {resp.status_code}")
if resp.status_code == 200:
    data = resp.json()
    print(f"Events count: {len(data.get('events', []))}")
