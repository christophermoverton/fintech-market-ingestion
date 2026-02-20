import subprocess
import sys

def run_ingestion_test():
    # Define the command as a list of arguments
    command = [
        sys.executable, "-m", "src.ingestion.backfill_1m",
        "--start", "2026-02-01",
        "--end", "2026-02-04",
        "--max-symbols", "5",
        "--sleep-ms", "50"
    ]
    
    print(f"🚀 Running smoke test: {' '.join(command)}")
    
    try:
        # shell=False is more secure; capture_output=False lets you see the logs in real-time
        subprocess.run(command, check=True)
        print("\n✅ Ingestion test completed successfully.")
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Test failed with error code {e.returncode}")

if __name__ == "__main__":
    run_ingestion_test()