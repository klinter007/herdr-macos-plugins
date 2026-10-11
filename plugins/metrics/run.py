import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from herdr_tools.cli import main
sys.argv.insert(1, 'metrics')
raise SystemExit(main())
