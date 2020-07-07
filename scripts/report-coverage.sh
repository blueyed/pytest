#!/usr/bin/env bash

set -e
set -x

if ! [ -f coverage.xml ]; then
  if [ -z "$TOXENV" ]; then
    python -m pip install coverage
  else
    # Add last TOXENV to $PATH.
    PATH="$PWD/.tox/${TOXENV##*,}/bin:$PATH"
  fi

  python -m coverage combine
  python -m coverage xml
  python -m coverage report -m
fi

# Set --connect-timeout to work around https://github.com/curl/curl/issues/4461
curl -S -L --connect-timeout 5 --retry 6 -s -o codecov.sh \
  https://raw.githubusercontent.com/codecov/codecov-bash/af362d8bc/codecov
bash codecov.sh -Z -X fix -f coverage.xml "$@"
