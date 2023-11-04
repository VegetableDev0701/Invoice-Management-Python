#!/bin/bash

# Save the old PYTHONPATH
OLD_PYTHONPATH=$PYTHONPATH

# Modify the PYTHONPATH to include your project root
export PYTHONPATH=/Users/mgrant/STAK/app/stak-backend/api:$PYTHONPATH

# Run pytest
pytest --log-level=DEBUG -s -vv

# Restore the original PYTHONPATH
export PYTHONPATH=$OLD_PYTHONPATH
