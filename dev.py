"""
TapTalent Dev Runner — Starts Backend, Frontend, and Agent in a single terminal.

Usage:
    python dev.py
"""

import os
import subprocess
import sys
import time

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

def main():
    print("=" * 60)
    print(" 🚀 Starting TapTalent (Backend + Frontend + Agent)")
    print("=" * 60)

    processes = []

    try:
        # 1. Backend (Node/Express - Port 3000)
        print("\n[1/3] Starting Backend (http://localhost:3000)...")
        backend_proc = subprocess.Popen(
            ["npm", "run", "dev"],
            cwd=os.path.join(ROOT_DIR, "backend"),
            shell=True
        )
        processes.append(("Backend", backend_proc))
        time.sleep(1)

        # 2. Frontend (Vite/React - Port 5173)
        print("\n[2/3] Starting Frontend (http://localhost:5173)...")
        frontend_proc = subprocess.Popen(
            ["npm", "run", "dev"],
            cwd=os.path.join(ROOT_DIR, "frontend"),
            shell=True
        )
        processes.append(("Frontend", frontend_proc))
        time.sleep(1)

        # 3. Agent (Python LiveKit Worker)
        print("\n[3/3] Starting LiveKit Agent Worker...")
        agent_proc = subprocess.Popen(
            [sys.executable, "agent.py", "dev"],
            cwd=os.path.join(ROOT_DIR, "agent"),
            shell=False
        )
        processes.append(("Agent", agent_proc))

        print("\n" + "=" * 60)
        print(" ✅ All services running! Press Ctrl+C to stop all.")
        print(" 🌐 Frontend: http://localhost:5173")
        print(" 🔌 Backend:  http://localhost:3000")
        print("=" * 60 + "\n")

        # Wait for all
        while True:
            for name, p in processes:
                if p.poll() is not None:
                    print(f"\n⚠️ Process {name} exited with code {p.returncode}")
            time.sleep(1)

    except KeyboardInterrupt:
        print("\n\n🛑 Stopping all services...")
        for name, p in processes:
            try:
                p.terminate()
            except Exception:
                pass
        print("All processes stopped.")

if __name__ == "__main__":
    main()
