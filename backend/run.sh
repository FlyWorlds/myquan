#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [[ -z "${JAVA_HOME:-}" ]]; then
  if [[ -x /opt/homebrew/opt/openjdk/libexec/openjdk.jdk/Contents/Home/bin/java ]]; then
    export JAVA_HOME=/opt/homebrew/opt/openjdk/libexec/openjdk.jdk/Contents/Home
  elif [[ -x /usr/libexec/java_home ]]; then
    export JAVA_HOME="$(/usr/libexec/java_home)"
  fi
fi
if [[ -n "${JAVA_HOME:-}" ]]; then
  export PATH="$JAVA_HOME/bin:$PATH"
fi
if ! command -v mvn >/dev/null 2>&1; then
  echo "Maven 3.6.3+ is required." >&2
  exit 1
fi

case "${1:-run}" in
  run)
    exec mvn --no-transfer-progress "-Dspring-boot.run.jvmArguments=${BACKEND_JAVA_OPTS:--Xms128m -Xmx512m}" spring-boot:run
    ;;
  test)
    exec mvn --no-transfer-progress test
    ;;
  package)
    exec mvn --no-transfer-progress package
    ;;
  *)
    echo "Usage: bash backend/run.sh [run|test|package]" >&2
    exit 2
    ;;
esac
