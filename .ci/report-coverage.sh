#!/bin/sh
#
# Submit/report coverage when run from CI for "coverage" tox factors.

set -ex

if [ -z "$CI" ]; then
  exit
fi

# Set --connect-timeout to work around https://github.com/curl/curl/issues/4461
curl -S -L --connect-timeout 5 --retry 6 -s -o codecov.sh \
  https://raw.githubusercontent.com/blueyed/codecov-bash/my-master/codecov
bash codecov.sh -Z -X fix -f coverage.xml "$@"
