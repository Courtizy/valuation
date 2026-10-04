"""python -m valuation run AAPL --models dcf,comps | python -m valuation sector sic-of:AAPL"""
import sys

from valuation.runner import main

if __name__ == "__main__":
    sys.exit(main())
