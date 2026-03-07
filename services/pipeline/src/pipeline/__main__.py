# Thin wrapper — delegates to knowledge.pipeline
import logging
import sys

from knowledge.pipeline import index_ready, run

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if len(sys.argv) > 1 and sys.argv[1] == "index":
        index_ready()
    else:
        run()
