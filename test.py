import subprocess
import sys

if __name__ == "__main__":
    result = subprocess.run([sys.executable, "-m", "unittest", "tests/test.py"])
    sys.exit(result.returncode)
