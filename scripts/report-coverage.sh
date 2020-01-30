#!/usr/bin/env bash

set -e
set -x

if [ -z "$TOXENV" ]; then
  python -m pip install coverage
else
  # Add last TOXENV to $PATH.
  PATH="$PWD/.tox/${TOXENV##*,}/bin:$PATH"
fi

python -m coverage combine
python -m coverage xml
python -m coverage report -m

if command -v cc-test-reporter; then
  cc-test-reporter after-build
fi

# Set --connect-timeout to work around https://github.com/curl/curl/issues/4461
curl -S -L --connect-timeout 5 --retry 6 --retry-connrefused -s https://codecov.io/bash -o codecov-upload.sh
bash codecov-upload.sh -Z -X fix -f coverage.xml "$@"
