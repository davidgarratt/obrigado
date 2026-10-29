#!/usr/bin/env python3
"""
Obrigado - Launcher Script
Run: python run.py [--port 8000] [--host 0.0.0.0]
"""
import sys
import io

# Ensure UTF-8 output on all platforms (including Windows cp1252 terminal)
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except AttributeError:
        pass

import socket
import argparse
import uvicorn
from app.config import settings

def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((host, port)) == 0

def find_available_port(preferred_port: int) -> int:
    port = preferred_port
    while is_port_in_use(port):
        print(f"⚠️ Port {port} is currently in use by another application.")
        port += 1
    return port

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run MindGraph PA")
    parser.add_argument("--port", type=int, default=settings.port, help="Port to run server on")
    parser.add_argument("--host", type=str, default=settings.host, help="Host to bind server to")
    args = parser.parse_args()

    port = args.port
    if is_port_in_use(port):
        fallback_port = find_available_port(8050 if port == 8000 else port + 1)
        print(f"🔄 Automatically routing Obrigado to port {fallback_port} to prevent conflict.")
        port = fallback_port

    print("=" * 60)
    print(f"🚀 Launching {settings.app_name} v{settings.app_version}")
    print(f"📡 Serving on: http://{args.host}:{port} (Local: http://localhost:{port})")
    print(f"🤖 Gemini LLM: {settings.llm_model} | Embeddings: {settings.embedding_model}")
    print(f"🌐 Tailscale Mesh: Connect via Tailscale IP or run `tailscale serve --bg {port}`")
    print("=" * 60)

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=port,
        reload=settings.debug,
        log_level="info"
    )
