#!/bin/sh
# Check that there are __init__.pyi / __init__.py files for all dirs
# (especially in testing, for mypy to consider it with "mypy testing").

ret=0
for d in $(git ls-tree -dr --name-only HEAD src testing); do
  if [ "$d" = src ] || [ -f "$d/__init__.pyi" ] || [ -f "$d/__init__.py" ]; then
    continue
  fi
  ret=1
  echo "missing __init__.py{,i}: $d"
done
exit $ret
