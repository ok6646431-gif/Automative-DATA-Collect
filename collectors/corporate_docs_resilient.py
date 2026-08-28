"""Run the official-document collector with a longer read window for large verified files.

Some first-party ESG/sustainability servers establish the connection normally but
serve 20-40 MB PDFs slowly enough that the base collector's short evidence-lane timeout
can expire mid-transfer. This wrapper changes only bounded transport settings; payload
validation, source verification, extension allowlists and size limits remain unchanged.
"""

import sys

import corporate_docs_collect as base

# Keep connect failures bounded while allowing slow first-party large PDFs to finish.
base.DOWNLOAD_TIMEOUT = (10, 90)
base.DOWNLOAD_ATTEMPTS = 2


if __name__ == "__main__":
    sys.exit(base.main())
