#!/bin/sh
# Pull catalog message files from Transifex

[ -n "$GITHUB_ACTIONS" ] && set -x
set -e

# Allow language being passed as 1st argument, defaults to ja
LANGUAGE=${1:-ja}

ROOTDIR=$(dirname $0)/..

cd ${ROOTDIR}

if ! test -f cpython/Doc/conf.py; then
  echo Unable to find proper CPython Doc folder
  exit 1
fi

# Create POT Files
cd cpython/Doc
sphinx-build -E -b gettext -D gettext_compact=0 -d build/.doctrees . locales/pot

# Update CPython's .tx/config
cd  locales
sphinx-intl create-txconfig
sphinx-intl update-txconfig-resources -p pot -d . --transifex-project-name python-newest

# Update the translation project's .tx/config
cd ../../..     # back to $ROOTDIR
mkdir -p .tx
sed cpython/Doc/locales/.tx/config \
  -e '/^source_file/d' \
  -e 's|<lang>/LC_MESSAGES/||' \
  -e "s|^file_filter|trans.${LANGUAGE}|" \
  > .tx/config

tx pull -l ${LANGUAGE} --use-git-timestamps --parallel
